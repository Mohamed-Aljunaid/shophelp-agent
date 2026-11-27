"""Placeholders for the optional providers. They will implement the same Provider interface."""
from llm.base import Provider


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, **kwargs):
        super().__init__(model, **kwargs)
        raise NotImplementedError("AnthropicProvider is not implemented yet; use LLM_PROVIDER=gemini")


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: str, model: str, **kwargs):
        super().__init__(model, **kwargs)
        raise NotImplementedError("OpenAIProvider is not implemented yet; use LLM_PROVIDER=gemini")
