"""Modelos de salida de la API de documentos."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import DocumentStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    sha256: str
    size_bytes: int
    status: DocumentStatus
    error_code: str | None
    error_message: str | None
    page_count: int | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime


class UploadOut(DocumentOut):
    # True si el mismo archivo ya existía en la organización.
    duplicate: bool = False


class DocumentListOut(BaseModel):
    items: list[DocumentOut]


class ChunkOut(BaseModel):
    """Fragmento fuente de una cita."""

    id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page_number: int
    content: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    trace_id: str


class ErrorOut(BaseModel):
    error: ErrorDetail
