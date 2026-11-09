"""Doküman indexing servisi: chunk + embed + chunks tablosuna yazma."""

import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import BASE_DIR
from app.core.llm import get_embeddings
from app.models.document import Chunk, Document, PDFImage, PDFPage, PDFTable
from app.services.chunking import chunk_text_hierarchical
from app.services.pdf_parser import PDFIngestionService
from app.services.vision import VisionService

logger = logging.getLogger(__name__)

# Cloudflare Workers AI embedding batch sınırı (100 metin/istek) altında kal.
EMBED_BATCH_SIZE = 100


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
        sıralı işlendiği için doküman sırası korunur). Embedding'ler batch
        halinde (en fazla 100) gönderilir — bulut sağlayıcıda sayfa başına
        ayrı HTTP çağrısı yapılmaz, index süresi ciddi kısalır.
        """
        pending: list[tuple[PDFPage, dict]] = []  # (sayfa, chunk parçası)
        for page in pages:
            if not page.raw_text:
                continue
            pending.extend((page, piece) for piece in chunk_text_hierarchical(page.raw_text))

        chunks_added = 0
        for batch_start in range(0, len(pending), EMBED_BATCH_SIZE):
            batch = pending[batch_start : batch_start + EMBED_BATCH_SIZE]
            embeddings = self.embeddings.embed_documents([p["content"] for _, p in batch])
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
                        bbox=page.bbox,
                    )
                    for i, ((page, piece), embedding) in enumerate(
                        zip(batch, embeddings, strict=True), start=batch_start
                    )
                ]
            )
        chunks_added += len(pending)
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
                    bbox=table.bbox,
                )
                for table, content, embedding in zip(tables, contents, embeddings, strict=True)
            ]
        )
        return len(tables)

    async def ingest_images(self, images: list[PDFImage]) -> int:
        """Görselleri Vision ile açıklar, chunk_type="image" ile embed eder.

        Vision hatasında (API down, timeout, anahtar boş) placeholder
        fallback yazılır — pipeline çökmez; reindex_images ile sonradan
        gerçek açıklamayla doldurulabilir.
        """
        if not images:
            return 0
        vision = VisionService()
        contents: list[str] = []
        for image in images:
            contents.append(await self._describe_image_content(vision, image))
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
                    bbox=image.bbox,
                )
                for image, content, embedding in zip(images, contents, embeddings, strict=True)
            ]
        )
        return len(images)

    async def reindex_images(self, document_id: UUID) -> int | None:
        """Dokümanın image chunk'larını Vision ile yeniden açıklar (backfill).

        Placeholder'lı/eski açıklamalı image chunk'lar bulunur; her biri
        yeniden açıklanıp content + embedding güncellenir. Doküman yoksa None.
        """
        doc = await self._get_owned_document(document_id)
        if doc is None:
            return None
        chunks = list(
            (
                await self.db.scalars(
                    select(Chunk).where(
                        Chunk.document_id == document_id, Chunk.chunk_type == "image"
                    )
                )
            ).all()
        )
        if not chunks:
            return 0

        ref_ids = [c.source_ref_id for c in chunks if c.source_ref_id]
        images = {
            img.id: img
            for img in (
                await self.db.scalars(
                    select(PDFImage)
                    .where(PDFImage.id.in_(ref_ids))
                    .options(selectinload(PDFImage.page))
                )
            ).all()
        }

        vision = VisionService()
        updated = 0
        for chunk in chunks:
            image = images.get(chunk.source_ref_id) if chunk.source_ref_id else None
            if image is None:
                continue
            new_content = await self._describe_image_content(vision, image)
            chunk.content = new_content
            chunk.embedding = self.embeddings.embed_documents([new_content])[0]
            updated += 1
        await self.db.commit()
        return updated

    async def _describe_image_content(self, vision: VisionService, image: PDFImage) -> str:
        """Görsel için Vision açıklamalı chunk content'i üretir (fallback'li)."""
        image_type = image.image_type or "unknown"
        try:
            description = await vision.describe_image(self._resolve_image_path(image), image_type)
        except Exception as exc:  # noqa: BLE001 (spec: tek görsel hatası akışı bozmasın)
            logger.warning("Vision açıklaması alınamadı (%s): %s", image.id, exc)
            description = f"[görsel açıklaması alınamadı: {exc}]"
        return f"Page {image.page.page_number} — {image_type}: {description}"

    @staticmethod
    def _resolve_image_path(image: PDFImage) -> Path:
        """DB'deki (portatif) görsel yolunu mutlak yola çevirir."""
        path = Path(image.image_path or "")
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

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
