"""Gemini provider (google-genai SDK) with function calling."""
import json
import uuid

from google import genai
from google.genai import errors, types

from llm.base import LLMError, LLMResponse, Provider

RETRYABLE_CODES = {429, 500, 502, 503, 504}


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, **kwargs):
        super().__init__(model, **kwargs)
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set (see .env.example)")
        self.client = genai.Client(api_key=api_key)

    def _chat(self, system, messages, tools) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"],
                                          parameters_json_schema=t["parameters"])
                for t in tools
            ])] if tools else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = self.client.models.generate_content(model=self.model, contents=to_contents(messages), config=config)
        return from_response(resp)

    def _is_retryable(self, exc: Exception) -> bool:
        return isinstance(exc, errors.APIError) and exc.code in RETRYABLE_CODES


def to_contents(messages: list[dict]) -> list[types.Content]:
    """Convert neutral messages to Gemini contents, merging consecutive same-role turns."""
    contents: list[types.Content] = []
    for m in messages:
        if m["role"] == "assistant" and (m.get("provider_data") or {}).get("gemini_content"):
            content = types.Content.model_validate(m["provider_data"]["gemini_content"])  # keeps thought signatures
        elif m["role"] == "assistant":
            parts = [types.Part(text=m["content"])] if m.get("content") else []
            parts += [types.Part(function_call=types.FunctionCall(id=c["id"], name=c["name"], args=c["args"]))
                      for c in m.get("tool_calls") or []]
            content = types.Content(role="model", parts=parts)
        elif m["role"] == "tool":
            content = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                id=m["tool_call_id"], name=m["name"], response={"result": m["content"]}))])
        elif m["role"] == "user":
            content = types.Content(role="user", parts=[types.Part(text=m["content"])])
        else:
            raise ValueError(f"unknown role: {m['role']}")
        if contents and contents[-1].role == content.role:
            contents[-1].parts.extend(content.parts)
        else:
            contents.append(content)
    return contents


def from_response(resp: types.GenerateContentResponse) -> LLMResponse:
    """Pull text and tool calls out of a Gemini response."""
    if not resp.candidates or not resp.candidates[0].content or not resp.candidates[0].content.parts:
        reason = resp.candidates[0].finish_reason if resp.candidates else getattr(resp, "prompt_feedback", None)
        raise LLMError(f"Gemini returned no content ({reason})")
    content = resp.candidates[0].content
    text = "".join(p.text for p in content.parts if p.text and not p.thought) or None
    calls = []
    for p in content.parts:
        if p.function_call:
            if not p.function_call.id:
                p.function_call.id = uuid.uuid4().hex[:12]  # Gemini may omit ids; we need them to match results
            calls.append({"id": p.function_call.id, "name": p.function_call.name,
                          "args": dict(p.function_call.args or {})})
    data = json.loads(json.dumps(content.model_dump(mode="json", exclude_none=True)))
    return LLMResponse(text=text, tool_calls=calls, provider_data={"gemini_content": data})
