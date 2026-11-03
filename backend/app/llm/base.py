"""Contrato común de los proveedores de LLM."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResult:
    text: str  # respuesta cruda del modelo (se espera JSON)
    model: str
    tokens_input: int
    tokens_output: int
    retries: int = 0  # reintentos internos del proveedor (429, 5xx)


class LLMProvider(Protocol):
    name: str

    def generate(self, system: str, user: str) -> LLMResult: ...


class LLMError(Exception):
    """Base de los errores del proveedor de LLM."""


class LLMTimeoutError(LLMError):
    """El proveedor no respondió a tiempo (se traduce a 504)."""


class LLMRateLimitError(LLMError):
    """El proveedor limitó las peticiones (se traduce a 429)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMProviderError(LLMError):
    """Cualquier otro fallo del proveedor (se traduce a 502)."""
