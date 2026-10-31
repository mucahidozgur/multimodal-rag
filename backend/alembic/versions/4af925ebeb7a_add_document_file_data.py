"""add document file_data

Revision ID: 4af925ebeb7a
Revises: 795e680a8637
Create Date: 2026-10-31 17:02:31.749922

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4af925ebeb7a"
down_revision: str | None = "795e680a8637"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Faz 7: PDF baytlarının DB kopyası (Render free tier geçici diski silse
    # bile dosya Neon'dan geri yüklenebilir).
    op.add_column("documents", sa.Column("file_data", sa.LargeBinary(), nullable=True))
    # Not: ix_chunks_tsv_content (BM25) index'i metadata'da tanımlı olmadığı
    # için autogenerate onu "silinecek" gördü; elle korundu (drop yapılmadı).


def downgrade() -> None:
    op.drop_column("documents", "file_data")
