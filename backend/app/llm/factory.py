"""Selección del proveedor de LLM según LLM_PROVIDER."""

from functools import lru_cache

import openai

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.mock import MockProvider
from app.llm.openai_provider import OpenAIProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "mock":
        return MockProvider()
    if settings.openai_api_key is None:  # Settings ya lo valida; esto es para mypy
        raise ValueError("LLM_PROVIDER=openai requiere OPENAI_API_KEY")
    client = openai.OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=0,  # los reintentos los gestiona OpenAIProvider con tenacity
    )
    return OpenAIProvider(client, settings.openai_model, settings.llm_timeout_seconds)
