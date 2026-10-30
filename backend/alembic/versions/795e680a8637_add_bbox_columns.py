"""add bbox columns

Revision ID: 795e680a8637
Revises: 4a1b42eb1268
Create Date: 2026-10-30 17:16:58.607924

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "795e680a8637"
down_revision: str | None = "4a1b42eb1268"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Faz 4: citation bounding box'ları [x0, top, x1, bottom] (PDF nokta).
    op.add_column("chunks", sa.Column("bbox", sa.JSON(), nullable=True))
    op.add_column("pdf_pages", sa.Column("bbox", sa.JSON(), nullable=True))
    op.add_column("pdf_tables", sa.Column("bbox", sa.JSON(), nullable=True))
    op.add_column("pdf_images", sa.Column("bbox", sa.JSON(), nullable=True))
    # Not: ix_chunks_tsv_content (BM25) index'i metadata'da tanımlı olmadığı
    # için autogenerate onu "silinecek" gördü; elle korundu (drop yapılmadı).


def downgrade() -> None:
    op.drop_column("pdf_images", "bbox")
    op.drop_column("pdf_tables", "bbox")
    op.drop_column("pdf_pages", "bbox")
    op.drop_column("chunks", "bbox")
