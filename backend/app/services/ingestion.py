"""Doküman indexing servisi: chunk + embed + chunks tablosuna yazma."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.llm import get_embeddings
from app.models.document import Chunk, Document, PDFImage, PDFPage, PDFTable
from app.services.chunking import chunk_text_hierarchical
from app.services.pdf_parser import PDFIngestionService


class DocumentIngestionService:
    """Dokümanı chunk'layıp embedding'lerini chunks tablosuna yazar."""

    def __init__(self, db: AsyncSession, owner_id: UUID) -> None:
        self.db = db
        self.owner_id = owner_id
        self.embeddings = get_embeddings()

    async def index_document(self, document_id: UUID) -> dict | None:
        """Dokümanı index'ler; varsa eski chunk'ları siler. Doküman yoksa None."""
        doc = await self._get_owned_document(document_id)
        if doc is None:
            return None

        result = await self.db.execute(delete(Chunk).where(Chunk.document_id == document_id))
        chunks_deleted = result.rowcount or 0

        chunks = chunk_text_hierarchical(doc.content)
        if chunks:
            embeddings = self.embeddings.embed_documents([c["content"] for c in chunks])
            self.db.add_all(
                [
                    Chunk(
                        document_id=document_id,
                        content=chunk["content"],
                        embedding=embedding,
                        chunk_index=chunk["chunk_index"],
                        heading=chunk["heading"],
                    )
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ]
            )

        await self.db.commit()
        return {
            "document_id": document_id,
            "chunks_created": len(chunks),
            "chunks_deleted": chunks_deleted,
        }

    async def _get_owned_document(self, document_id: UUID) -> Document | None:
        """Dokümanı owner filtresiyle getirir."""
        stmt = select(Document).where(
            Document.id == document_id, Document.owner_id == self.owner_id
        )
        return await self.db.scalar(stmt)

    # --- Faz 2: multi-modal ingestion (text + table + image) ---

    async def ingest_text_pages(self, pages: list[PDFPage]) -> int:
        """Sayfa metinlerini chunk'layıp embed eder (chunk_type="text").

        chunk_index doküman genelinde akan bir sayaçla verilir (sayfalar
        sıralı işlendiği için doküman sırası korunur).
        """
        chunks_added = 0
        for page in pages:
            if not page.raw_text:
                continue
            pieces = chunk_text_hierarchical(page.raw_text)
            if not pieces:
                continue
            embeddings = self.embeddings.embed_documents([p["content"] for p in pieces])
            self.db.add_all(
                [
                    Chunk(
                        document_id=page.document_id,
                        content=piece["content"],
                        embedding=embedding,
                        chunk_index=chunks_added + i,
                        heading=piece["heading"],
                        chunk_type="text",
                        source_ref_id=page.id,
                        page_number=page.page_number,
                    )
                    for i, (piece, embedding) in enumerate(zip(pieces, embeddings, strict=True))
                ]
            )
            chunks_added += len(pieces)
        return chunks_added

    async def ingest_tables(self, tables: list[PDFTable]) -> int:
        """Tablo markdown'larını embed eder (chunk_type="table").

        İçeriğin başına "Page {n} — Table {i}: " context header'ı eklenir;
        retrieval sırasında chunk tek başına da bağlamını taşır.
        """
        if not tables:
            return 0
        contents = [
            f"Page {table.page.page_number} — Table {table.table_index}: "
            f"{table.markdown_content}"
            for table in tables
        ]
        embeddings = self.embeddings.embed_documents(contents)
        self.db.add_all(
            [
                Chunk(
                    document_id=table.page.document_id,
                    content=content,
                    embedding=embedding,
                    chunk_index=table.table_index or 0,
                    heading=None,
                    chunk_type="table",
                    source_ref_id=table.id,
                    page_number=table.page.page_number,
                )
                for table, content, embedding in zip(tables, contents, embeddings, strict=True)
            ]
        )
        return len(tables)

    async def ingest_images(self, images: list[PDFImage]) -> int:
        """Görsel description placeholder'larını embed eder (chunk_type="image").

        Faz 3'te description VLM ile gerçek grafik okumasıyla doldurulacak.
        """
        if not images:
            return 0
        contents = [
            f"Page {image.page.page_number} — {image.image_type}: " "[görsel açıklaması yakında]"
            for image in images
        ]
        embeddings = self.embeddings.embed_documents(contents)
        self.db.add_all(
            [
                Chunk(
                    document_id=image.page.document_id,
                    content=content,
                    embedding=embedding,
                    chunk_index=image.image_index or 0,
                    heading=None,
                    chunk_type="image",
                    source_ref_id=image.id,
                    page_number=image.page.page_number,
                )
                for image, content, embedding in zip(images, contents, embeddings, strict=True)
            ]
        )
        return len(images)

    async def ingest_document_with_pdf(self, document_id: UUID) -> dict | None:
        """PDF'i parse edip text/table/image chunk'larını tek seferde index'ler.

        Akış: parse_pdf → PDF kayıtları (sayfa/tablo/görsel) → her tip ayrı
        embed edilir. Eski chunk'lar silinir (idempotent). Doküman yoksa None;
        file_path set değilse ValueError.
        """
        doc = await self._get_owned_document(document_id)
        if doc is None:
            return None
        if not doc.file_path:
            raise ValueError("Document has no file_path")

        await PDFIngestionService(self.db).parse_document(doc)

        await self.db.execute(delete(Chunk).where(Chunk.document_id == document_id))

        pages = list(
            (await self.db.scalars(select(PDFPage).where(PDFPage.document_id == document_id))).all()
        )
        tables = list(
            (
                await self.db.scalars(
                    select(PDFTable)
                    .join(PDFPage, PDFPage.id == PDFTable.page_id)
                    .where(PDFPage.document_id == document_id)
                    .options(selectinload(PDFTable.page))
                )
            ).all()
        )
        images = list(
            (
                await self.db.scalars(
                    select(PDFImage)
                    .join(PDFPage, PDFPage.id == PDFImage.page_id)
                    .where(PDFPage.document_id == document_id)
                    .options(selectinload(PDFImage.page))
                )
            ).all()
        )

        text_chunks = await self.ingest_text_pages(pages)
        table_chunks = await self.ingest_tables(tables)
        image_chunks = await self.ingest_images(images)
        await self.db.commit()
        return {
            "text_chunks": text_chunks,
            "table_chunks": table_chunks,
            "image_chunks": image_chunks,
        }
