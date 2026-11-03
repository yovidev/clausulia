"""Proveedor OpenAI con el SDK oficial (Responses API y Structured Outputs)."""

import copy
import time
from collections.abc import Callable
from typing import Any

import openai
import structlog
from openai.types.responses import Response
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt
from tenacity.wait import wait_exponential

from app.llm.base import LLMProviderError, LLMRateLimitError, LLMResult, LLMTimeoutError
from app.schemas.ask import LLMAnswer

log = structlog.get_logger(__name__)

MAX_RETRIES = 3
MAX_RETRY_AFTER = 30.0  # no se bloquea una petición más de esto por un Retry-After


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        timeout: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # El cliente debe crearse con max_retries=0: los reintentos los controla tenacity.
        self._client = client
        self.model = model
        self._timeout = timeout
        self._backoff = wait_exponential(multiplier=1, max=8)
        self._retrying = Retrying(
            stop=stop_after_attempt(1 + MAX_RETRIES),
            wait=self._wait,
            retry=retry_if_exception(_is_retryable),
            sleep=sleep,
            before_sleep=lambda state: log.warning(
                "llm_retry", attempt=state.attempt_number, provider=self.name
            ),
            reraise=True,
        )

    def generate(self, system: str, user: str) -> LLMResult:
        attempts = 0

        def attempt() -> Response:
            # Contador local a la llamada: seguro aunque varias peticiones compartan el proveedor.
            nonlocal attempts
            attempts += 1
            return self._create(system, user)

        try:
            response = self._retrying(attempt)
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError("OpenAI no respondió a tiempo") from exc
        except openai.RateLimitError as exc:
            raise LLMRateLimitError(
                "OpenAI limitó las peticiones", retry_after=_retry_after(exc)
            ) from exc
        except openai.APIError as exc:
            raise LLMProviderError(f"Error del proveedor OpenAI: {type(exc).__name__}") from exc

        usage = response.usage
        return LLMResult(
            text=response.output_text,
            model=response.model,
            tokens_input=usage.input_tokens if usage else 0,
            tokens_output=usage.output_tokens if usage else 0,
            retries=attempts - 1,
        )

    def _create(self, system: str, user: str) -> Response:
        return self._client.responses.create(
            model=self.model,
            instructions=system,
            input=user,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "llm_answer",
                    "schema": _STRICT_SCHEMA,
                    "strict": True,
                }
            },
            store=False,  # los contratos no se guardan en OpenAI
            timeout=self._timeout,
        )

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, openai.RateLimitError):
            retry_after = _retry_after(exc)
            if retry_after is not None:
                return min(retry_after, MAX_RETRY_AFTER)
        return float(self._backoff(state))


def _is_retryable(exc: BaseException) -> bool:
    """Se reintenta ante 429 y 5xx; el resto (400, 401, timeout...) falla enseguida."""
    return isinstance(exc, openai.APIStatusError) and (
        exc.status_code == 429 or exc.status_code >= 500
    )


def _retry_after(exc: openai.APIStatusError) -> float | None:
    headers = exc.response.headers
    for header, divisor in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        value = headers.get(header)
        if value is None:
            continue
        try:
            return max(float(value) / divisor, 0.0)
        except ValueError:
            continue  # p. ej. una fecha HTTP: se usa el backoff normal
    return None


def _strict_schema() -> dict[str, Any]:
    """Structured Outputs en modo estricto exige todos los campos obligatorios y sin defaults."""
    schema = copy.deepcopy(LLMAnswer.model_json_schema())
    schema["required"] = list(schema["properties"])
    for prop in schema["properties"].values():
        prop.pop("default", None)
    return schema


_STRICT_SCHEMA = _strict_schema()
