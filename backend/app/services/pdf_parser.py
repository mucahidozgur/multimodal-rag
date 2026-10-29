"""PDF ayrıştırma servisi: metin + tablo (pdfplumber), görsel (PyMuPDF).

Faz 1: Finansal PDF'lerden (10-K/10-Q) ham malzemeyi çıkarır; Faz 2'deki
multi-modal indexleme bu çıktının üzerine kurulacak.
"""

import asyncio
import uuid
from pathlib import Path

import pdfplumber
import pymupdf
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, PDFImage, PDFPage, PDFTable

# Boyut bazlı görsel tipi eşikleri (Faz 3'te VLM ile değiştirilecek).
CHART_MIN_WIDTH = 300
CHART_MIN_HEIGHT = 150
LOGO_MAX_SIZE = 100


def table_to_markdown(table: list[list[str | None]]) -> str:
    """Tablo hücrelerini markdown formatına çevirir (ilk satır başlık)."""
    rows = [
        [(cell or "").replace("\n", "<br>").replace("|", "\\|") for cell in row] for row in table
    ]
    if not rows:
        return ""
    header = rows[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def classify_image(width: int, height: int) -> str:
    """Boyut bazlı görsel tipi tahmini.

    Geniş + uzun → "chart", küçük kare → "logo", diğer → "figure".
    Faz 3'te gerçek tip VLM ile belirlenecek.
    """
    if width >= CHART_MIN_WIDTH and height >= CHART_MIN_HEIGHT:
        return "chart"
    if width <= LOGO_MAX_SIZE and height <= LOGO_MAX_SIZE:
        return "logo"
    return "figure"


def _extract_tables(page: pdfplumber.page.Page) -> list[list[list[str | None]]]:
    """Sayfadaki tabloları çıkarır (pdfplumber varsayılan "lines" stratejisi).

    Faz 1 kapsamında çizgi çizilmiş tablolar hedeftir (10-K'lardaki gibi;
    reportlab GRID de çizgi üretir). Tüm hücreleri boş olan sahte tablolar
    elenir. Kenarlıksız tablolar gerekirse Faz 2'de camelot (stream) ile
    ele alınacak.
    """
    tables = page.extract_tables()
    return [t for t in tables if any(cell for row in t for cell in row if cell)]


class PDFParser:
    """PDF'ten metin, tablo ve görsel çıkarır."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self.storage_dir = Path(storage_dir or get_settings().STORAGE_DIR)
        self.images_dir = self.storage_dir / "images"

    async def parse_pdf(self, pdf_path: str | Path) -> dict:
        """PDF'i ayrıştırır.

        pdfplumber/PyMuPDF senkron kütüphanelerdir; event loop'u bloklamamak
        için ayrıştırma işi bir thread'e devredilir.

        Returns:
            {
                "pages": [
                    {
                        "page_number": 1,
                        "text": "...",
                        "tables": [{"data": [[...]], "markdown": "..."}],
                        "images": [{"path": "storage/images/...", "type": "...",
                                    "width": ..., "height": ...}],
                    }
                ]
            }
        """
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF dosyası bulunamadı: {path}")
        return await asyncio.to_thread(self._parse_sync, path)

    def _parse_sync(self, path: Path) -> dict:
        """pdfplumber ile metin/tablo, PyMuPDF ile görsel çıkarır (sync)."""
        pages: list[dict] = []
        fitz_doc = pymupdf.open(str(path))
        try:
            with pdfplumber.open(str(path)) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    pages.append(
                        {
                            "page_number": i,
                            "text": page.extract_text() or "",
                            "tables": [
                                {"data": t, "markdown": table_to_markdown(t)}
                                for t in _extract_tables(page)
                            ],
                            "images": self._extract_page_images(fitz_doc, i - 1),
                        }
                    )
        finally:
            fitz_doc.close()
        return {"pages": pages}

    def _extract_page_images(self, doc: pymupdf.Document, page_index: int) -> list[dict]:
        """Sayfadaki gömülü görselleri diske yazar, meta bilgileri döndürür."""
        images: list[dict] = []
        page = doc[page_index]
        for xref, *_ in page.get_images(full=True):
            info = doc.extract_image(xref)
            if not info:
                continue
            ext = info.get("ext") or "png"
            width = int(info.get("width") or 0)
            height = int(info.get("height") or 0)
            filename = f"{uuid.uuid4().hex}.{ext}"
            self.images_dir.mkdir(parents=True, exist_ok=True)
            (self.images_dir / filename).write_bytes(info["image"])
            # DB'ye portatif yol yaz: storage kökünün bir üstüne göre (backend/).
            rel_path = self.images_dir / filename
            try:
                rel_path = rel_path.relative_to(self.storage_dir.parent)
            except ValueError:
                pass  # storage_dir dışı bir yolsa mutlak yol olarak kalır
            images.append(
                {
                    "path": str(rel_path).replace("\\", "/"),
                    "type": classify_image(width, height),
                    "width": width,
                    "height": height,
                }
            )
        return images


class PDFIngestionService:
    """parse-pdf sonucunu DB'ye yazar: PDFPage/PDFTable/PDFImage kayıtları."""

    def __init__(self, db: AsyncSession, parser: PDFParser | None = None) -> None:
        self.db = db
        self.parser = parser or PDFParser()

    async def parse_document(self, document: Document) -> dict:
        """Dokümanın PDF'ini ayrıştırıp kaydeder.

        Eski sayfa kayıtlarını siler (idempotent re-parse). PDF diskte yoksa
        FileNotFoundError yükseltir.
        """
        if not document.file_path:
            raise ValueError("Document has no file_path")
        result = await self.parser.parse_pdf(document.file_path)

        await self.db.execute(delete(PDFPage).where(PDFPage.document_id == document.id))
        tables_found = 0
        images_found = 0
        for page in result["pages"]:
            page_row = PDFPage(
                document_id=document.id,
                page_number=page["page_number"],
                raw_text=page["text"],
            )
            self.db.add(page_row)
            await self.db.flush()  # tablo/görsel satırları için page id gerekli
            for i, table in enumerate(page["tables"]):
                tables_found += 1
                self.db.add(
                    PDFTable(
                        page_id=page_row.id,
                        table_index=i,
                        data_json=table["data"],
                        markdown_content=table["markdown"],
                    )
                )
            for i, image in enumerate(page["images"]):
                images_found += 1
                self.db.add(
                    PDFImage(
                        page_id=page_row.id,
                        image_index=i,
                        image_path=image["path"],
                        image_type=image["type"],
                        width=image["width"],
                        height=image["height"],
                    )
                )
        await self.db.commit()
        return {
            "pages_parsed": len(result["pages"]),
            "tables_found": tables_found,
            "images_found": images_found,
        }
