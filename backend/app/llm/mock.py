"""Proveedor de LLM simulado y determinista: funciona sin claves ni red."""

import html
import re
from typing import Literal

from app.llm.base import LLMRateLimitError, LLMResult, LLMTimeoutError
from app.schemas.ask import LLMAnswer

FailureMode = Literal["invalid_json", "invalid_json_once", "timeout", "rate_limit"]

_CHUNK = re.compile(r'<chunk id="([^"]*)"[^>]*>(.*?)</chunk>', re.DOTALL)
_SNIPPET_CHARS = 300


class MockProvider:
    name = "mock"
    model = "mock-1"

    def __init__(self, failure: FailureMode | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def generate(self, system: str, user: str) -> LLMResult:
        self.calls += 1
        if self.failure == "timeout":
            raise LLMTimeoutError("El proveedor simulado no respondió a tiempo")
        if self.failure == "rate_limit":
            raise LLMRateLimitError("Límite de peticiones simulado", retry_after=1.0)
        if self.failure == "invalid_json" or (
            self.failure == "invalid_json_once" and self.calls == 1
        ):
            return self._result(system, user, "Esto no es JSON {")
        return self._result(system, user, self._answer(user).model_dump_json())

    @staticmethod
    def _answer(user: str) -> LLMAnswer:
        # Los bloques llegan en el orden de la recuperación: por similitud en modo vector,
        # por Reciprocal Rank Fusion en modo hybrid. Cita siempre el primero.
        match = _CHUNK.search(user)
        if match is None:
            return LLMAnswer(
                answer="No hay evidencia suficiente en los documentos para responder.",
                citations=[],
                confidence="low",
                insufficient_evidence=True,
            )
        chunk_id, content = html.unescape(match.group(1)), html.unescape(match.group(2))
        return LLMAnswer(
            answer=f"Según el documento: {content.strip()[:_SNIPPET_CHARS]}",
            citations=[chunk_id],
            confidence="medium",
            insufficient_evidence=False,
        )

    def _result(self, system: str, user: str, text: str) -> LLMResult:
        return LLMResult(
            text=text,
            model=self.model,
            tokens_input=len(system + user) // 4,
            tokens_output=len(text) // 4,
        )
