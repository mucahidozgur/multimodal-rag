"""SQLAlchemy ORM modelleri: Document, Chunk ve PDF ayrıştırma modelleri."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Computed, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.core.db import Base


class Document(Base):
    """Doküman; chunk'ları ve PDF sayfalarıyla bire-çok ilişkili."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="upload")
    # Faz 1: PDF dosyasının disk üzerindeki yolu (parse-pdf endpoint'i buradan okur).
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )
    pages: Mapped[list["PDFPage"]] = relationship(
        "PDFPage", back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """Doküman parçası; pgvector embedding'i saklar."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(get_settings().EMBEDDING_DIM))
    chunk_index: Mapped[int] = mapped_column(Integer)
    # Hiyerarşik chunking: chunk'ın ait olduğu başlık zinciri ("Ana > Alt").
    # Eski (Faz 0-2) chunk'lar için None kalabilir.
    heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Faz 2: chunk'ın kaynak tipi ("text" | "table" | "image") ve hangi PDF
    # kaydından geldiği (PDFPage/PDFTable/PDFImage id) + citation için sayfa.
    chunk_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text", index=True)
    source_ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Faz 4: chunk kaynağının sayfa üzerindeki konumu [x0, top, x1, bottom].
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # FTS (BM25) araması için generated column: content her yazıldığında DB
    # tarafında to_tsvector('simple', content) ile otomatik güncellenir.
    tsv_content: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple'::regconfig, content)", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")


class PDFPage(Base):
    """PDF'in tek sayfası: ham metin + sayfadaki tablolar ve görseller (Faz 1)."""

    __tablename__ = "pdf_pages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)  # Çıkarılan ham metin
    # Faz 4: sayfanın tam boyutu [x0, top, x1, bottom] (PDF nokta birimi).
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="pages")
    tables: Mapped[list["PDFTable"]] = relationship(
        "PDFTable", back_populates="page", cascade="all, delete-orphan"
    )
    images: Mapped[list["PDFImage"]] = relationship(
        "PDFImage", back_populates="page", cascade="all, delete-orphan"
    )


class PDFTable(Base):
    """Sayfadan çıkarılan tablo: JSON hücreler + markdown gösterimi."""

    __tablename__ = "pdf_tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pdf_pages.id", ondelete="CASCADE")
    )
    table_index: Mapped[int | None] = mapped_column(Integer)  # Sayfadaki kaçıncı tablo
    data_json: Mapped[list | None] = mapped_column(JSON)  # [[cell1, cell2], [cell3, cell4]]
    markdown_content: Mapped[str | None] = mapped_column(Text)  # Tablo markdown olarak
    # Faz 4: tablonun sayfa üzerindeki konumu [x0, top, x1, bottom].
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)

    page: Mapped["PDFPage"] = relationship("PDFPage", back_populates="tables")


class PDFImage(Base):
    """Sayfadan çıkarılan görsel; dosya diskte, meta bilgiler DB'de."""

    __tablename__ = "pdf_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pdf_pages.id", ondelete="CASCADE")
    )
    image_index: Mapped[int | None] = mapped_column(Integer)  # Sayfadaki kaçıncı görsel
    image_path: Mapped[str | None] = mapped_column(String)  # storage/images/{uuid}.png
    image_type: Mapped[str | None] = mapped_column(String)  # "chart", "figure", "logo", "unknown"
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    # Faz 4: görselin sayfa üzerindeki konumu [x0, top, x1, bottom].
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)

    page: Mapped["PDFPage"] = relationship("PDFPage", back_populates="images")
