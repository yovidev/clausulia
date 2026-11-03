"""Conversión de texto a vectores (embeddings)."""

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.db.models import EMBEDDING_DIM

_WORD = re.compile(r"\w+")


class Embedder(Protocol):
    name: str  # modelo usado, para las trazas

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Modelo local multilingüe vía fastembed (ONNX, sin PyTorch ni claves)."""

    def __init__(self, model_name: str, cache_dir: str | None, batch_size: int) -> None:
        from fastembed import TextEmbedding  # import diferido: cargar el modelo tarda

        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.name = model_name
        self._batch_size = batch_size
        dim = len(self.embed_query("prueba"))
        if dim != EMBEDDING_DIM:
            raise ValueError(
                f"El modelo {model_name} produce vectores de {dim} dimensiones; "
                f"la base de datos espera {EMBEDDING_DIM}"
            )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.embed(texts, batch_size=self._batch_size)
        return [[float(x) for x in vector] for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class FakeEmbedder:
    """Embedding determinista para pruebas: cada palabra suma en una posición del vector.

    Textos que comparten palabras quedan cerca. No entiende sinónimos; para eso está
    el modelo real.
    """

    name = "fake"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIM
        for word in _WORD.findall(text.lower()):
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            # Un vector de ceros no tiene dirección y la similitud coseno no está definida.
            vector[0] = 1.0
            return vector
        return [x / norm for x in vector]


@lru_cache
def get_embedder() -> Embedder:
    """Una sola instancia por proceso: cargar el modelo tarda varios segundos."""
    settings = get_settings()
    if settings.embedding_provider == "fake":
        return FakeEmbedder()
    return FastEmbedEmbedder(
        settings.embedding_model, settings.embedding_cache_dir, settings.embedding_batch_size
    )
