import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import EMBEDDING_DIM, Document, DocumentStatus

pytestmark = pytest.mark.integration

BEFORE_TSV = "06991eb44464"


def _column_exists(engine: Engine) -> bool:
    query = text(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'chunks' AND column_name = 'content_tsv'"
    )
    with engine.connect() as connection:
        return bool(connection.execute(query).scalar_one())


def _index_exists(engine: Engine) -> bool:
    query = text("SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_chunks_content_tsv'")
    with engine.connect() as connection:
        return bool(connection.execute(query).scalar_one())


def test_content_tsv_migration_fills_existing_rows_and_downgrade_removes_it(
    engine: Engine, session_factory: sessionmaker[Session]
) -> None:
    config = Config("alembic.ini")
    command.downgrade(config, BEFORE_TSV)
    try:
        assert not _column_exists(engine)
        # Datos creados antes de que exista la columna.
        with session_factory() as session, session.begin():
            document = Document(
                organization_id="org-a",
                filename="contrato.pdf",
                sha256=uuid.uuid4().hex,
                size_bytes=1,
                status=DocumentStatus.READY,
            )
            session.add(document)
            session.flush()
            # SQL directo: el modelo ya incluye content_tsv y el ORM la pediría en RETURNING.
            session.execute(
                text(
                    "INSERT INTO chunks (id, document_id, chunk_index, page_number, content, "
                    "embedding) VALUES (:id, :document_id, 0, 1, :content, :embedding)"
                ),
                {
                    "id": uuid.uuid4(),
                    "document_id": document.id,
                    "content": "El preaviso de resolución será de noventa días naturales.",
                    "embedding": str([1.0] + [0.0] * (EMBEDDING_DIM - 1)),
                },
            )

        command.upgrade(config, "head")

        assert _index_exists(engine)
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT content_tsv::text AS tsv, "
                    "content_tsv @@ websearch_to_tsquery('spanish', 'preavisos') AS hit "
                    "FROM chunks"
                )
            ).one()
        # Calculada para la fila existente, con stemming en español (preaviso → preavis).
        assert "'preavis'" in row.tsv
        assert row.hit

        command.downgrade(config, BEFORE_TSV)
        assert not _column_exists(engine)
        assert not _index_exists(engine)
        with engine.connect() as connection:
            # Los chunks siguen ahí: el downgrade solo quita la columna.
            assert connection.execute(text("SELECT count(*) FROM chunks")).scalar_one() == 1
    finally:
        command.upgrade(config, "head")
