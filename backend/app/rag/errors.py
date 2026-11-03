"""Errores del dominio de preguntas. No saben de HTTP: main.py los traduce a status."""

import uuid


class DocumentNotFoundError(Exception):
    """Documentos pedidos que no existen o son de otra organización."""

    def __init__(self, document_ids: list[uuid.UUID]) -> None:
        super().__init__(f"Documentos no encontrados: {document_ids}")
        self.document_ids = document_ids


class DocumentNotReadyError(Exception):
    """Documentos pedidos que existen pero aún no están listos para consultar."""

    def __init__(self, document_ids: list[uuid.UUID]) -> None:
        super().__init__(f"Documentos no listos: {document_ids}")
        self.document_ids = document_ids
