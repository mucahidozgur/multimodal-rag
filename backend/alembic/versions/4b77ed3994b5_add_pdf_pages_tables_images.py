"""add pdf pages tables images

Revision ID: 4b77ed3994b5
Revises: d2050e320bc2
Create Date: 2026-10-25 23:21:53.428038

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b77ed3994b5"
down_revision: str | None = "d2050e320bc2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Faz 1: PDF ayrıştırma — sayfa, tablo ve görsel kayıtları.
    op.create_table(
        "pdf_pages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pdf_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("page_id", sa.UUID(), nullable=False),
        sa.Column("image_index", sa.Integer(), nullable=True),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("image_type", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["page_id"], ["pdf_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pdf_tables",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("page_id", sa.UUID(), nullable=False),
        sa.Column("table_index", sa.Integer(), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("markdown_content", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["page_id"], ["pdf_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Not: ix_chunks_tsv_content (BM25) index'i metadata'da tanımlı olmadığı
    # için autogenerate onu "silinecek" gördü; elle korundu (drop yapılmadı).
    op.add_column("documents", sa.Column("file_path", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "file_path")
    op.drop_table("pdf_tables")
    op.drop_table("pdf_images")
    op.drop_table("pdf_pages")
