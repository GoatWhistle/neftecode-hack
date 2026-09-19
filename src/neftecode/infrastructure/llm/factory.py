import os
from typing import Mapping

from neftecode.application.ports.llm import LLMClient, LLMError

from .anthropic import AnthropicClient
from .config import KEY_OPTIONAL, KEY_VARIABLES, LLMSettings
from .openai_compatible import OpenAICompatibleClient

MODEL_VARIABLES = {"zai": "ZAI_MODEL", "openai": "OPENAI_MODEL", "anthropic": "ANTHROPIC_MODEL",
                   "local": "LOCAL_LLM_MODEL"}


def _refuse(message: str) -> LLMError:
    return LLMError("not_configured", message)


def make_llm_client(settings: LLMSettings, environ: Mapping[str, str] = os.environ) -> LLMClient:
    provider = settings.provider
    if provider == "scripted":
        raise _refuse("scripted client must be injected explicitly")
    if "PYTEST_CURRENT_TEST" in environ and environ.get("LLM_ALLOW_LIVE_IN_TESTS") != "1":
        raise _refuse("live providers are disabled under pytest (LLM_ALLOW_LIVE_IN_TESTS=1 to allow)")
    if provider not in KEY_VARIABLES:
        raise _refuse(f"неизвестный LLM_PROVIDER {provider!r}; ожидается zai, openai, anthropic или scripted")
    if not settings.api_key and provider not in KEY_OPTIONAL:
        raise _refuse(f"не задан ключ провайдера {provider}: {' / '.join(KEY_VARIABLES[provider])}")
    if not settings.model:
        raise _refuse(f"не задана модель провайдера {provider}: {MODEL_VARIABLES[provider]}")
    common = dict(model=settings.model, api_key=settings.api_key, temperature=settings.temperature,
                  max_retries=settings.max_retries)
    if provider == "anthropic":
        return AnthropicClient(settings.base_url, **common)
    if provider == "zai" and "/api/coding/" not in settings.base_url and not settings.allow_general_endpoint:
        raise _refuse("ZAI_BASE_URL не является Coding Plan endpoint (/api/coding/): General API списывает "
                      "платный баланс; задайте ZAI_ALLOW_GENERAL_ENDPOINT=1, если это намеренно")
    return OpenAICompatibleClient(provider, settings.base_url, **common)
