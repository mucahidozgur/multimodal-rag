"""add chunk multimodal fields

Revision ID: 4a1b42eb1268
Revises: 4b77ed3994b5
Create Date: 2026-10-29 21:46:44.926371

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a1b42eb1268"
down_revision: str | None = "4b77ed3994b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Faz 2: chunk kaynak tipi + PDF kaynak referansı + sayfa (citation).
    # server_default: mevcut (Faz 0-1) chunk satırları "text" kabul edilir.
    op.add_column(
        "chunks",
        sa.Column("chunk_type", sa.String(length=20), server_default="text", nullable=False),
    )
    op.add_column("chunks", sa.Column("source_ref_id", sa.UUID(), nullable=True))
    op.add_column("chunks", sa.Column("page_number", sa.Integer(), nullable=True))
    # Not: ix_chunks_tsv_content (BM25) index'i metadata'da tanımlı olmadığı
    # için autogenerate onu "silinecek" gördü; elle korundu (drop yapılmadı).
    op.create_index(op.f("ix_chunks_chunk_type"), "chunks", ["chunk_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chunks_chunk_type"), table_name="chunks")
    op.drop_column("chunks", "page_number")
    op.drop_column("chunks", "source_ref_id")
    op.drop_column("chunks", "chunk_type")
