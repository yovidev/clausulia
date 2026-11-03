import math

import pytest

from app.db.models import EMBEDDING_DIM
from app.ingestion.embeddings import FakeEmbedder, FastEmbedEmbedder


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_fake_embedder_is_deterministic_and_normalized() -> None:
    embedder = FakeEmbedder()
    first = embedder.embed_query("Renovación automática del contrato")
    second = embedder.embed_query("Renovación automática del contrato")
    assert first == second
    assert len(first) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in first)), 1.0)


def test_fake_embedder_puts_texts_with_shared_words_closer() -> None:
    embedder = FakeEmbedder()
    query = embedder.embed_query("penalización por retraso en la entrega")
    related = embedder.embed_query("La penalización por retraso será del 2% semanal")
    unrelated = embedder.embed_query("Los tribunales de Madrid tendrán jurisdicción")
    assert _cosine(query, related) > _cosine(query, unrelated)


def test_fake_embedder_handles_empty_text() -> None:
    vector = FakeEmbedder().embed_query("")
    assert any(x != 0 for x in vector)


@pytest.mark.model
def test_real_model_understands_paraphrases_in_spanish() -> None:
    embedder = FastEmbedEmbedder(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_dir=".models",
        batch_size=8,
    )
    query = embedder.embed_query("renovación automática del contrato")
    paraphrase = embedder.embed_query("el acuerdo se prorrogará tácitamente por periodos iguales")
    unrelated = embedder.embed_query("los tribunales de Madrid serán competentes")
    assert len(query) == EMBEDDING_DIM
    assert _cosine(query, paraphrase) > _cosine(query, unrelated)
