"""chunks.content_tsv para búsqueda full-text

Revision ID: a3f1c2d4e5b6
Revises: 06991eb44464
Create Date: 2026-11-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f1c2d4e5b6"
down_revision: str | Sequence[str] | None = "06991eb44464"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Añade la columna generada y su índice GIN.

    STORED: Postgres la calcula al añadirla para todas las filas existentes (reescribe la
    tabla) y la mantiene en cada INSERT o UPDATE de content.
    """
    op.add_column(
        "chunks",
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('spanish', content)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_chunks_content_tsv", "chunks", ["content_tsv"], unique=False, postgresql_using="gin"
    )


def downgrade() -> None:
    """Elimina el índice y la columna; los chunks y sus embeddings no se tocan."""
    op.drop_index("ix_chunks_content_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "content_tsv")
