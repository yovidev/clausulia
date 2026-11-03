"""Recuperación de fragmentos por similitud coseno. Solo recupera: no llama al LLM."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from opentelemetry import trace
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.telemetry import timed_span
from app.db.models import Chunk, Document, DocumentStatus
from app.ingestion.embeddings import Embedder

tracer = trace.get_tracer(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page_number: int
    content: str
    similarity: float  # 1 - distancia coseno


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]  # los k más cercanos, de mayor a menor similitud
    relevant: list[RetrievedChunk]  # los que superan el umbral


def search_chunks(
    session: Session,
    embedder: Embedder,
    question: str,
    organization_id: str,
    k: int,
    threshold: float,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> RetrievalResult:
    """Devuelve los k chunks más cercanos a la pregunta dentro de la organización.

    Activa el escaneo iterativo de HNSW solo en la transacción actual (SET LOCAL).
    """
    with timed_span(tracer, "embed_query", {"embeddings.model": embedder.name}):
        vector = embedder.embed_query(question)
    with timed_span(
        tracer, "pgvector.search", {"search.k": k, "search.threshold": threshold}
    ) as span:
        # El índice no conoce la organización: filtra después de elegir candidatos y podría
        # dejar menos de k. El escaneo iterativo sigue buscando, en orden exacto por distancia.
        session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        # <=> en SQL: el mismo operador que el índice HNSW (vector_cosine_ops).
        distance = Chunk.embedding.cosine_distance(vector).label("distance")

        query = (
            select(
                Chunk.id,
                Chunk.document_id,
                Document.filename,
                Chunk.page_number,
                Chunk.content,
                distance,
            )
            .join(Document, Chunk.document_id == Document.id)
            .where(
                Document.organization_id == organization_id,
                Document.status == DocumentStatus.READY,
            )
            .order_by(distance)
            .limit(k)
        )
        if document_ids is not None:
            query = query.where(Chunk.document_id.in_(document_ids))

        chunks = [
            RetrievedChunk(
                chunk_id=row.id,
                document_id=row.document_id,
                document_name=row.filename,
                page_number=row.page_number,
                content=row.content,
                similarity=round(1.0 - float(row.distance), 4),
            )
            for row in session.execute(query)
        ]
        relevant = [c for c in chunks if c.similarity >= threshold]
        span.set_attribute("chunks.retrieved", len(chunks))
        span.set_attribute("chunks.relevant", len(relevant))
        if chunks:
            span.set_attribute("similarity.top", chunks[0].similarity)
    return RetrievalResult(chunks=chunks, relevant=relevant)
