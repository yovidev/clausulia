"""Modelos de la pregunta, la respuesta del LLM y la respuesta de la API."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Confidence = Literal["high", "medium", "low"]


class AskIn(BaseModel):
    # Se recortan los espacios antes de validar la longitud.
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)
    ]
    # None = todos los documentos de la organización; una lista vacía no tiene sentido.
    document_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=50)


class LLMAnswer(BaseModel):
    """Respuesta basada solo en los chunks proporcionados, con los ids de los chunks citados."""

    # Esta docstring llega al modelo como "description" del esquema JSON.
    # Estricto: sin campos extra ni coerciones (por ejemplo, "true" no vale como booleano).
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str
    citations: list[str]  # ids de chunk
    confidence: Confidence
    insufficient_evidence: bool
    has_conflict: bool = False


class CitationOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page: int
    snippet: str


class AskOut(BaseModel):
    status: Literal["answered", "insufficient_evidence", "rejected"]
    answer: str | None
    citations: list[CitationOut]
    confidence: Confidence | None
    has_conflict: bool = False
