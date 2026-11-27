"""Provider-neutral chat interface with throttling, retry and a disk cache.

Messages are plain JSON-friendly dicts, so they fit in LangGraph state and the cache:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str | None, "tool_calls": [{"id", "name", "args"}], "provider_data": ...}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Tools are {"name", "description", "parameters": <JSON schema>}.
`provider_data` is opaque: a provider stores what it needs to replay its own turn
(e.g. Gemini thought signatures). Other code must pass it through untouched.
"""
import hashlib
import json
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


class LLMError(Exception):
    """The model call failed or returned nothing usable."""


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[dict] = field(default_factory=list)  # [{"id", "name", "args"}]
    provider_data: dict | None = None

    def to_message(self) -> dict:
        """The assistant message to append to the conversation."""
        return {"role": "assistant", "content": self.text, "tool_calls": self.tool_calls,
                "provider_data": self.provider_data}


class Provider:
    """Base class: subclasses implement _chat and _is_retryable."""

    name = "base"

    def __init__(self, model: str, max_rpm: int = 10, max_retries: int = 5, cache_path: Path | None = None):
        if not model:
            raise LLMError(f"No model name set for {self.name} (see .env.example)")
        self.model = model
        self.max_retries = max_retries
        self._interval = 60.0 / max_rpm if max_rpm > 0 else 0.0
        self._last_call = 0.0
        self._lock = threading.Lock()
        self._cache = _Cache(cache_path) if cache_path else None
        self.cache_salt = ""  # e.g. the eval trial number, so repeated trials are not replays

    def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        """Send the conversation; return text and/or tool calls."""
        tools = tools or []
        key = _key(self.name, self.model, self.cache_salt, system, messages, tools)
        if self._cache and (hit := self._cache.get(key)):
            return LLMResponse(**hit)
        response = self._with_retry(system, messages, tools)
        if self._cache:
            self._cache.put(key, response.__dict__)
        return response

    def _with_retry(self, system, messages, tools) -> LLMResponse:
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                return self._chat(system, messages, tools)
            except Exception as exc:
                if attempt == self.max_retries or not self._is_retryable(exc):
                    raise LLMError(f"{self.name} call failed: {type(exc).__name__}: {exc}") from exc
                time.sleep(min(60.0, 2.0 * 2**attempt) + random.random())  # backoff + jitter
        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        """Keep requests under max_rpm (free-tier limits)."""
        with self._lock:
            wait = self._last_call + self._interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        raise NotImplementedError

    def _is_retryable(self, exc: Exception) -> bool:
        return False


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class _Cache:
    """Tiny SQLite key-value store for LLM responses."""

    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def get(self, key: str) -> dict | None:
        row = self._conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        with self._conn:
            self._conn.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, json.dumps(value)))
