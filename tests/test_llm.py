"""LLM layer: Gemini message conversion, retry, throttle, cache, factory. No network
except test_gemini_live, which runs only when GEMINI_API_KEY and GEMINI_MODEL are set."""
import pytest
from google.genai import errors, types

from config import Settings, settings
from llm import LLMError, get_provider
from llm.base import LLMResponse, Provider
from llm.gemini import from_response, to_contents

TOOL = {"name": "get_order_details", "description": "Get an order.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}


def test_to_contents_maps_roles_and_merges_tool_results():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "name": "f", "args": {"x": 1}}, {"id": "b", "name": "g", "args": {}}]},
        {"role": "tool", "tool_call_id": "a", "name": "f", "content": "1"},
        {"role": "tool", "tool_call_id": "b", "name": "g", "content": "2"},
    ]
    contents = to_contents(msgs)
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert [p.function_response.name for p in contents[2].parts] == ["f", "g"]  # one turn for both results
    assert contents[1].parts[0].function_call.args == {"x": 1}


def gemini_response(*parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])


def test_from_response_keeps_thought_signature_for_replay():
    resp = gemini_response(
        types.Part(text="thinking...", thought=True),
        types.Part(function_call=types.FunctionCall(name="get_order_details", args={"order_id": "#W1"}),
                   thought_signature=b"sig"),
    )
    out = from_response(resp)
    assert out.text is None  # thoughts are not shown
    assert out.tool_calls[0]["name"] == "get_order_details" and out.tool_calls[0]["id"]
    replay = to_contents([out.to_message()])[0]
    assert replay.parts[1].thought_signature == b"sig"
    assert replay.parts[1].function_call.id == out.tool_calls[0]["id"]


def test_from_response_reads_token_usage():
    resp = gemini_response(types.Part(text="hi"))
    resp.usage_metadata = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=120, candidates_token_count=8, thoughts_token_count=30)
    assert from_response(resp).usage == {"input_tokens": 120, "output_tokens": 38}  # thinking counts as output
    assert from_response(gemini_response(types.Part(text="hi"))).usage == {}


def test_from_response_empty_raises():
    with pytest.raises(LLMError):
        from_response(types.GenerateContentResponse(candidates=[]))


class Fake(Provider):
    name = "fake"

    def __init__(self, failures=0, retryable=True, **kw):
        super().__init__("fake-model", max_rpm=0, **kw)
        self.failures, self.retryable, self.calls = failures, retryable, 0

    def _chat(self, system, messages, tools):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("boom")
        return LLMResponse(text=f"reply {self.calls}")

    def _is_retryable(self, exc):
        return self.retryable


def test_retry_then_success(monkeypatch):
    monkeypatch.setattr("llm.base.time.sleep", lambda s: None)
    p = Fake(failures=2, max_retries=3)
    assert p.chat("sys", [{"role": "user", "content": "x"}]).text == "reply 3"


def test_no_retry_on_permanent_error_and_gives_up(monkeypatch):
    monkeypatch.setattr("llm.base.time.sleep", lambda s: None)
    with pytest.raises(LLMError, match="boom"):
        Fake(failures=1, retryable=False).chat("sys", [])
    p = Fake(failures=10, max_retries=2)
    with pytest.raises(LLMError):
        p.chat("sys", [])
    assert p.calls == 3


def test_cache_hit_skips_call(tmp_path):
    p = Fake(cache_path=tmp_path / "c.sqlite")
    msgs = [{"role": "user", "content": "x"}]
    assert p.chat("sys", msgs).text == "reply 1"
    hit = p.chat("sys", msgs)
    assert hit.text == "reply 1" and hit.cached and p.calls == 1
    assert p.chat("other", msgs).text == "reply 2"
    p.cache_salt = "trial2"
    assert p.chat("sys", msgs).text == "reply 3"  # a new trial is not served from cache


def test_throttle_spaces_calls(monkeypatch):
    slept = []
    monkeypatch.setattr("llm.base.time.sleep", slept.append)
    p = Fake()
    p._interval = 6.0  # 10 requests per minute
    p.chat("s", [{"role": "user", "content": "1"}])
    p.chat("s", [{"role": "user", "content": "2"}])
    assert slept and slept[0] > 5


def test_gemini_retryable_codes():
    from llm.gemini import GeminiProvider
    p = GeminiProvider.__new__(GeminiProvider)
    assert p._is_retryable(errors.APIError(429, {}))
    assert not p._is_retryable(errors.APIError(400, {}))


def test_factory():
    with pytest.raises(LLMError, match="model"):
        get_provider(Settings(_env_file=None, llm_provider="gemini", gemini_api_key="k"))
    with pytest.raises(LLMError, match="Unknown"):
        get_provider(Settings(_env_file=None, llm_provider="nope"))
    with pytest.raises(NotImplementedError):
        get_provider(Settings(_env_file=None, llm_provider="anthropic", anthropic_model="m"))
    assert get_provider(Settings(_env_file=None, gemini_api_key="k", gemini_model="m", llm_cache=False)).name == "gemini"


@pytest.mark.skipif(not (settings.gemini_api_key and settings.gemini_model), reason="needs GEMINI_API_KEY and GEMINI_MODEL")
def test_gemini_live():
    p = get_provider(Settings(llm_cache=False))
    msgs = [{"role": "user", "content": "What is the status of order #W2611340? Use the tool."}]
    first = p.chat("You are a shop assistant.", msgs, [TOOL])
    assert first.tool_calls and first.tool_calls[0]["name"] == "get_order_details"
    msgs += [first.to_message(), {"role": "tool", "tool_call_id": first.tool_calls[0]["id"],
                                  "name": "get_order_details", "content": '{"status": "processed"}'}]
    assert "processed" in p.chat("You are a shop assistant.", msgs, [TOOL]).text.lower()


def test_tracing_env_only_with_key(monkeypatch):
    from config import apply_tracing_env
    for var in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    assert not apply_tracing_env(Settings(_env_file=None, langsmith_tracing=True))  # no key: stays off
    assert "LANGSMITH_TRACING" not in __import__("os").environ
    assert apply_tracing_env(Settings(_env_file=None, langsmith_tracing=True, langsmith_api_key="k"))
    assert __import__("os").environ["LANGSMITH_PROJECT"] == "shophelp-agent"


def test_trace_payloads_skip_prompt_and_provider_data():
    from llm.base import _trace_inputs, _trace_outputs
    ins = _trace_inputs({"self": object(), "system": "x" * 2000, "tools": [TOOL],
                         "messages": [{"role": "assistant", "content": "hi", "provider_data": {"big": 1}}]})
    assert ins == {"messages": [{"role": "assistant", "content": "hi"}], "tools": ["get_order_details"],
                   "system_chars": 2000}
    out = _trace_outputs(LLMResponse(text="ok", usage={"input_tokens": 10, "output_tokens": 5}))
    assert out["usage_metadata"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
