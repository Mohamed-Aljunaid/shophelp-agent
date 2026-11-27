"""Local monitoring: an append-only event log (JSON lines) and a per-conversation report.

Events (all carry "ts" and "session"):
  llm         latency_ms, input_tokens, output_tokens, cached, tool_calls
  llm_error   latency_ms, error
  tool        name, ok, error
  escalation  kind=transfer | approval (amount, approved)
  guardrail   bypass attempt flagged in the customer's message

Report: uv run python -m agent.monitor [--last N]
"""
import argparse
import json
import threading
import time
from collections import defaultdict
from pathlib import Path

from config import settings

_lock = threading.Lock()


def log_event(session: str, event_type: str, **fields) -> None:
    """Append one event to the log (EVENTS_LOG). Never raises: monitoring must not break a chat."""
    record = {"ts": round(time.time(), 3), "session": session, "type": event_type, **fields}
    try:
        path = Path(settings.events_log)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def read_events(path: Path | None = None) -> list[dict]:
    path = Path(path or settings.events_log)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a half-written line from a crash
    return events


def per_conversation(events: list[dict]) -> list[dict]:
    """Aggregate events by session, oldest conversation first."""
    rows = defaultdict(lambda: defaultdict(float))
    for e in events:
        r = rows[e["session"]]
        r["start"] = min(r.get("start") or e["ts"], e["ts"])
        if e["type"] == "llm":
            r["llm_calls"] += 1
            r["latency_ms"] += e.get("latency_ms", 0)
            r["input_tokens"] += e.get("input_tokens", 0)
            r["output_tokens"] += e.get("output_tokens", 0)
            r["cached"] += bool(e.get("cached"))
        elif e["type"] == "llm_error":
            r["llm_errors"] += 1
        elif e["type"] == "tool":
            r["tool_calls"] += 1
            r["tool_errors"] += not e.get("ok", True)
        elif e["type"] == "escalation" and e.get("kind") == "transfer":
            r["transfers"] += 1
        elif e["type"] == "escalation" and e.get("kind") == "approval":
            r["approvals"] += 1
            r["rejected"] += not e.get("approved")
        elif e["type"] == "guardrail":
            r["guardrail_flags"] += 1
    out = [{"session": s, **{k: (int(v) if k != "start" else v) for k, v in r.items()}} for s, r in rows.items()]
    for row in out:
        calls = row.get("llm_calls", 0)
        row["avg_latency_ms"] = round(row.get("latency_ms", 0) / calls) if calls else 0
    return sorted(out, key=lambda r: r["start"])


COLUMNS = [("session", "session", 12), ("llm_calls", "llm", 4), ("avg_latency_ms", "avg ms", 7),
           ("input_tokens", "tok in", 8), ("output_tokens", "tok out", 8), ("tool_calls", "tools", 5),
           ("tool_errors", "t.err", 5), ("llm_errors", "l.err", 5), ("transfers", "xfer", 4),
           ("approvals", "appr", 4), ("rejected", "rej", 3), ("guardrail_flags", "guard", 5)]


def print_report(rows: list[dict]) -> None:
    print("  ".join(f"{label:>{w}}" for _, label, w in COLUMNS))
    for r in rows:
        print("  ".join(f"{str(r.get(k, 0))[:w]:>{w}}" for k, _, w in COLUMNS))
    if rows:
        total = {k: sum(r.get(k, 0) for r in rows) for k, _, _ in COLUMNS[1:]}
        calls = total["llm_calls"]
        total["avg_latency_ms"] = round(sum(r.get("latency_ms", 0) for r in rows) / calls) if calls else 0
        print("  ".join(f"{str(total.get(k, 'TOTAL' if k == 'session' else 0))[:w]:>{w}}" for k, _, w in COLUMNS))


def main() -> None:
    parser = argparse.ArgumentParser(description="Per-conversation monitoring report from the event log.")
    parser.add_argument("--last", type=int, default=20, help="show the N most recent conversations")
    parser.add_argument("--log", type=Path, help="event log (default: EVENTS_LOG)")
    args = parser.parse_args()
    rows = per_conversation(read_events(args.log))
    print(f"{len(rows)} conversations in {args.log or settings.events_log}; showing the last {args.last}")
    print_report(rows[-args.last:])


if __name__ == "__main__":
    main()
