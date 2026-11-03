"""Recuperación de fragmentos: coseno (vector) o coseno + full-text (hybrid). No llama al LLM."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from opentelemetry import trace
from sqlalchemy import ColumnElement, Select, Text, cast, func, select, text
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session

from app.core.telemetry import timed_span
from app.db.models import Chunk, Document, DocumentStatus
from app.ingestion.embeddings import Embedder

tracer = trace.get_tracer(__name__)

RetrievalMode = Literal["vector", "hybrid"]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page_number: int
    content: str
    similarity: float  # 1 - distancia coseno, real aunque el chunk venga solo del full-text


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]  # los k primeros, en orden de ranking
    best_similarity: float | None  # la mayor similitud entre ellos (None si no hay chunks)
    has_evidence: bool  # el mejor chunk llega al umbral: solo entonces se llama al LLM

    @classmethod
    def from_chunks(cls, chunks: list[RetrievedChunk], threshold: float) -> "RetrievalResult":
        best = max((c.similarity for c in chunks), default=None)
        return cls(chunks, best, best is not None and best >= threshold)


def search_chunks(
    session: Session,
    embedder: Embedder,
    question: str,
    organization_id: str,
    k: int,
    threshold: float,
    document_ids: Sequence[uuid.UUID] | None = None,
    *,
    mode: RetrievalMode = "vector",
    candidates: int = 20,
    rrf_k: int = 60,
) -> RetrievalResult:
    """Devuelve los k chunks mejor clasificados para la pregunta dentro de la organización.

    vector: los k más cercanos por distancia coseno, de mayor a menor similitud.
    hybrid: los `candidates` mejores por coseno y los `candidates` mejores por full-text se
    combinan con Reciprocal Rank Fusion y se devuelven los k primeros.

    Umbral: solo decide si hay evidencia, mirando la similitud coseno del mejor chunk. Si la
    hay, se devuelven los k para el LLM aunque alguno quede por debajo: un chunk con el dato
    exacto y similitud algo menor no se pierde, y coincidir por palabras nunca basta para
    pasar el umbral, porque la decisión se toma siempre con la similitud coseno.

    Activa el escaneo iterativo de HNSW solo en la transacción actual (SET LOCAL).
    """
    with timed_span(tracer, "embed_query", {"embeddings.model": embedder.name}):
        vector = embedder.embed_query(question)
    with timed_span(
        tracer,
        "pgvector.search",
        {"search.mode": mode, "search.k": k, "search.threshold": threshold},
    ) as span:
        # El índice no conoce la organización: filtra después de elegir candidatos y podría
        # dejar menos de los pedidos. El escaneo iterativo sigue buscando, en orden exacto.
        session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        # <=> en SQL: el mismo operador que el índice HNSW (vector_cosine_ops).
        distance = Chunk.embedding.cosine_distance(vector).label("distance")
        base = _base_query(distance, organization_id, document_ids)

        if mode == "vector":
            chunks = _rows(session, base.order_by(distance).limit(k))
        else:
            by_vector = _rows(session, base.order_by(distance).limit(candidates))
            by_text = _text_rows(session, base, question, candidates)
            chunks = _fuse([by_vector, by_text], rrf_k)[:k]
            span.set_attribute("chunks.text_matches", len(by_text))

        result = RetrievalResult.from_chunks(chunks, threshold)
        span.set_attribute("chunks.retrieved", len(chunks))
        span.set_attribute("evidence.sufficient", result.has_evidence)
        if result.best_similarity is not None:
            span.set_attribute("similarity.top", result.best_similarity)
    return result


def _base_query(
    distance: ColumnElement[Any],
    organization_id: str,
    document_ids: Sequence[uuid.UUID] | None,
) -> Select[Any]:
    """Columnas y filtros comunes a las dos ramas: organización, documentos listos y filtro."""
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
    )
    if document_ids is not None:
        query = query.where(Chunk.document_id.in_(document_ids))
    return query


def _text_rows(
    session: Session, base: Select[Any], question: str, limit: int
) -> list[RetrievedChunk]:
    """Rama full-text: chunks que comparten algún término con la pregunta, por ts_rank_cd.

    websearch_to_tsquery une los términos con AND (&); una pregunta en lenguaje natural casi
    nunca tiene todas sus palabras en un mismo chunk, así que se pasan a OR (|) y ts_rank_cd
    premia los chunks que reúnen más términos y más próximos. Las frases entre comillas
    conservan su operador de proximidad (<->).
    """
    strict = cast(func.websearch_to_tsquery("spanish", question), Text)
    # Cast directo a tsquery (no to_tsquery): los lexemas ya están normalizados y no se
    # vuelven a pasar por el stemmer.
    query = cast(func.replace(strict, "&", "|"), TSQUERY)
    rank = func.ts_rank_cd(Chunk.content_tsv, query)
    statement = base.where(Chunk.content_tsv.op("@@")(query)).order_by(rank.desc()).limit(limit)
    return _rows(session, statement)


def _rows(session: Session, statement: Select[Any]) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document_name=row.filename,
            page_number=row.page_number,
            content=row.content,
            similarity=round(1.0 - float(row.distance), 4),
        )
        for row in session.execute(statement)
    ]


def _fuse(rankings: list[list[RetrievedChunk]], rrf_k: int) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion: cada lista suma 1 / (rrf_k + posición) a sus chunks.

    Solo usa posiciones, no puntuaciones: la similitud coseno y ts_rank_cd no están en la
    misma escala. Empates: gana la mayor similitud coseno.
    """
    scores: dict[uuid.UUID, float] = {}
    merged: dict[uuid.UUID, RetrievedChunk] = {}
    for ranking in rankings:
        for position, chunk in enumerate(ranking, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (rrf_k + position)
            merged[chunk.chunk_id] = chunk
    return sorted(merged.values(), key=lambda c: (-scores[c.chunk_id], -c.similarity))
