"""Endpoints de documentos: subida, listado, detalle y fragmentos fuente."""

import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, BinaryIO

import structlog
from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Enqueuer, get_enqueuer, get_org_id
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.db.models import Chunk, Document, DocumentStatus
from app.db.session import get_db
from app.ingestion.storage import upload_path
from app.schemas.documents import ChunkOut, DocumentListOut, DocumentOut, ErrorOut, UploadOut

log = structlog.get_logger(__name__)
router = APIRouter(tags=["documents"])

PDF_MAGIC = b"%PDF-"
READ_BLOCK = 1024 * 1024  # 1 MB

DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorOut} for code in (404, 413, 415, 422, 503)
}


@router.post("/documents", status_code=202, response_model=UploadOut, responses={200: {}, **ERRORS})
def upload_document(
    file: Annotated[UploadFile, File()],
    response: Response,
    session: DbSession,
    org_id: OrgId,
    settings: Annotated[Settings, Depends(get_settings)],
    enqueue: Annotated[Enqueuer, Depends(get_enqueuer)],
) -> UploadOut:
    """Sube un PDF. 202 si es nuevo; 200 con duplicate=true si ya existía en la organización."""
    sha256, size = _save_upload(file.file, settings)
    filename = (file.filename or "documento.pdf")[:255]

    document = _find_existing(session, org_id, sha256)
    if document is None:
        document = Document(
            organization_id=org_id, filename=filename, sha256=sha256, size_bytes=size
        )
        session.add(document)
        try:
            session.commit()
        except IntegrityError:
            # Otra subida simultánea del mismo archivo ganó la carrera: se trata como duplicado.
            session.rollback()
            document = _find_existing(session, org_id, sha256)
            if document is None:
                raise
        else:
            log.info("document_uploaded", document_id=str(document.id), org_id=org_id)
            enqueue(document.id)
            return _upload_out(document, duplicate=False)

    response.status_code = 200
    if document.status == DocumentStatus.FAILED:
        # Se le da otra oportunidad: intentos a cero para que el barrido no lo descarte.
        document.status = DocumentStatus.PENDING
        document.error_code = None
        document.error_message = None
        document.attempts = 0
        session.commit()
        log.info("document_requeued", document_id=str(document.id), org_id=org_id)
        enqueue(document.id)
    else:
        session.commit()  # libera el bloqueo de _find_existing
    return _upload_out(document, duplicate=True)


@router.get("/documents", response_model=DocumentListOut, responses=ERRORS)
def list_documents(session: DbSession, org_id: OrgId) -> DocumentListOut:
    documents = session.scalars(
        select(Document)
        .where(Document.organization_id == org_id)
        .order_by(Document.created_at.desc(), Document.id)
    ).all()
    return DocumentListOut(items=[DocumentOut.model_validate(d) for d in documents])


@router.get("/documents/{document_id}", response_model=DocumentOut, responses=ERRORS)
def get_document(document_id: uuid.UUID, session: DbSession, org_id: OrgId) -> DocumentOut:
    document = session.scalars(
        select(Document).where(Document.id == document_id, Document.organization_id == org_id)
    ).one_or_none()
    if document is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Documento no encontrado")
    return DocumentOut.model_validate(document)


@router.get("/chunks/{chunk_id}", response_model=ChunkOut, responses=ERRORS)
def get_chunk(chunk_id: uuid.UUID, session: DbSession, org_id: OrgId) -> ChunkOut:
    row = session.execute(
        select(Chunk, Document.filename)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id == chunk_id, Document.organization_id == org_id)
    ).one_or_none()
    if row is None:
        raise ApiError(404, "CHUNK_NOT_FOUND", "Fragmento no encontrado")
    chunk, filename = row
    return ChunkOut(
        id=chunk.id,
        document_id=chunk.document_id,
        filename=filename,
        chunk_index=chunk.chunk_index,
        page_number=chunk.page_number,
        content=chunk.content,
    )


def _find_existing(session: Session, org_id: str, sha256: str) -> Document | None:
    # FOR UPDATE: dos duplicados simultáneos de un 'failed' no lo reencolan dos veces.
    return session.scalars(
        select(Document)
        .where(Document.organization_id == org_id, Document.sha256 == sha256)
        .with_for_update()
    ).one_or_none()


def _save_upload(source: BinaryIO, settings: Settings) -> tuple[str, int]:
    """Copia el archivo por bloques validando tamaño y tipo. Devuelve (sha256, bytes)."""
    max_bytes = settings.max_upload_mb * 1024 * 1024
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    size = 0
    # Temporal en el mismo directorio: el rename final es atómico (mismo sistema de archivos).
    with tempfile.NamedTemporaryFile(dir=upload_dir, suffix=".part", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            while block := source.read(READ_BLOCK):
                if size == 0 and not block.startswith(PDF_MAGIC):
                    raise ApiError(415, "UNSUPPORTED_FILE_TYPE", "El archivo no es un PDF")
                size += len(block)
                if size > max_bytes:
                    raise ApiError(
                        413,
                        "FILE_TOO_LARGE",
                        f"El archivo supera el máximo de {settings.max_upload_mb} MB",
                    )
                digest.update(block)
                tmp.write(block)
            if size == 0:
                raise ApiError(415, "UNSUPPORTED_FILE_TYPE", "El archivo está vacío")
        except BaseException:
            tmp.close()
            tmp_path.unlink(missing_ok=True)
            raise

    sha256 = digest.hexdigest()
    # Si ya existía, se sobrescribe con contenido idéntico (mismo hash).
    os.replace(tmp_path, upload_path(settings.upload_dir, sha256))
    return sha256, size


def _upload_out(document: Document, *, duplicate: bool) -> UploadOut:
    return UploadOut.model_validate(document).model_copy(update={"duplicate": duplicate})
