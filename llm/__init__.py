"""LLM provider interface: Gemini (default), Anthropic, OpenAI. Pick with LLM_PROVIDER."""
from config import Settings, settings as default_settings
from llm.base import LLMError, LLMResponse, Provider


def get_provider(s: Settings = default_settings) -> Provider:
    """Build the provider chosen in settings, with throttling, retry and cache."""
    common = dict(max_rpm=s.llm_max_requests_per_minute, max_retries=s.llm_max_retries,
                  cache_path=s.llm_cache_path if s.llm_cache else None)
    if s.llm_provider == "gemini":
        from llm.gemini import GeminiProvider
        return GeminiProvider(s.gemini_api_key, s.gemini_model, **common)
    if s.llm_provider == "anthropic":
        from llm.stubs import AnthropicProvider
        return AnthropicProvider(s.anthropic_api_key, s.anthropic_model, **common)
    if s.llm_provider == "openai":
        from llm.stubs import OpenAIProvider
        return OpenAIProvider(s.openai_api_key, s.openai_model, **common)
    raise LLMError(f"Unknown LLM_PROVIDER: {s.llm_provider}")


__all__ = ["get_provider", "LLMError", "LLMResponse", "Provider"]
