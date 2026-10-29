"""Faz 2 multi-modal ingestion + filtrelenebilir hybrid search testleri.

PDF'ler reportlab ile runtime'da üretilir; ingestion servisi test DB'sine
yazar, arama testleri API üzerinden yapılır.
"""

from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Image as RLImage,
)
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import deterministic_user_id
from app.models.document import Chunk, Document, PDFImage, PDFPage, PDFTable
from app.services.ingestion import DocumentIngestionService
from app.services.pdf_parser import PDFIngestionService

HYBRID_URL = "/api/ai/search/hybrid"

styles = getSampleStyleSheet()

# API arama testleri için: auth_headers "alice" için token üretir; dokümanların
# owner'ı da aynı deterministic id olmalı ki aramalarda görünsün.
ALICE_ID = UUID(deterministic_user_id("alice"))


def _build_pdf(path: Path, story: list) -> Path:
    """Verilen platypus öğelerinden PDF üretir."""
    SimpleDocTemplate(str(path), pagesize=letter).build(story)
    return path


def _make_png(path: Path, size: tuple[int, int] = (200, 150)) -> Path:
    img = PILImage.new("RGB", size, (20, 120, 200))
    img.save(path, format="PNG")
    return path


async def _create_parsed_document(
    db_session: AsyncSession, pdf_path: Path, owner_id: UUID = ALICE_ID
) -> Document:
    """Doküman oluşturur ve Faz 1 pipeline'ı ile PDF kayıtlarını yazar."""
    doc = Document(
        title=f"doc-{pdf_path.stem}",
        content="placeholder text content",
        owner_id=owner_id,
        file_path=str(pdf_path),
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    await PDFIngestionService(db_session).parse_document(doc)
    return doc


async def _chunks_of(db_session: AsyncSession, document_id: UUID) -> list[Chunk]:
    """Dokümanın chunk'larını chunk_index sırasıyla döndürür."""
    stmt = select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
    return list((await db_session.scalars(stmt)).all())


async def test_ingest_text_pages(tmp_path: Path, db_session: AsyncSession) -> None:
    """2 sayfalık PDF → her sayfadan en az 1 text chunk, doğru page_number."""
    pdf = _build_pdf(
        tmp_path / "text2.pdf",
        [
            Paragraph(
                "Customer satisfaction improved this quarter thanks to faster "
                "response times and better self-service documentation.",
                styles["Normal"],
            ),
            PageBreak(),
            Paragraph(
                "Operating expenses were reduced by consolidating vendor "
                "contracts across the finance and procurement departments.",
                styles["Normal"],
            ),
        ],
    )
    doc = await _create_parsed_document(db_session, pdf, owner_id=uuid4())
    pages = list(
        (await db_session.scalars(select(PDFPage).where(PDFPage.document_id == doc.id))).all()
    )
    service = DocumentIngestionService(db_session, doc.owner_id)
    added = await service.ingest_text_pages(pages)
    await db_session.commit()

    chunks = await _chunks_of(db_session, doc.id)
    assert added == len(chunks) >= 2
    assert all(c.chunk_type == "text" for c in chunks)
    assert {c.page_number for c in chunks} == {1, 2}
    assert all(c.source_ref_id in {p.id for p in pages} for c in chunks)


async def test_ingest_tables(tmp_path: Path, db_session: AsyncSession) -> None:
    """Tablolu PDF → table chunk; content header'ı sayfa ve tablo no taşır."""
    table = Table(
        [["Metric", "Q3 2025", "Q3 2026"], ["Revenue", "1.2M", "1.8M"]],
        colWidths=[100, 80, 80],
        style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]),
    )
    pdf = _build_pdf(tmp_path / "table.pdf", [Paragraph("Financials", styles["Title"]), table])
    doc = await _create_parsed_document(db_session, pdf, owner_id=uuid4())
    tables = list(
        (
            await db_session.scalars(
                select(PDFTable)
                .join(PDFPage, PDFPage.id == PDFTable.page_id)
                .where(PDFPage.document_id == doc.id)
                .options(selectinload(PDFTable.page))
            )
        ).all()
    )
    service = DocumentIngestionService(db_session, doc.owner_id)
    added = await service.ingest_tables(tables)
    await db_session.commit()

    chunks = await _chunks_of(db_session, doc.id)
    assert added == len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_type == "table"
    assert chunk.page_number == 1
    assert chunk.content.startswith("Page 1 — Table 0:")
    assert "Revenue" in chunk.content
    assert chunk.source_ref_id == tables[0].id


async def test_ingest_images(tmp_path: Path, db_session: AsyncSession) -> None:
    """Görselli PDF → image chunk (placeholder açıklamasıyla)."""
    png = _make_png(tmp_path / "fig.png", size=(400, 250))
    pdf = _build_pdf(tmp_path / "image.pdf", [RLImage(str(png), 400, 250)])
    doc = await _create_parsed_document(db_session, pdf, owner_id=uuid4())
    images = list(
        (
            await db_session.scalars(
                select(PDFImage)
                .join(PDFPage, PDFPage.id == PDFImage.page_id)
                .where(PDFPage.document_id == doc.id)
                .options(selectinload(PDFImage.page))
            )
        ).all()
    )
    service = DocumentIngestionService(db_session, doc.owner_id)
    added = await service.ingest_images(images)
    await db_session.commit()

    chunks = await _chunks_of(db_session, doc.id)
    assert added == len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_type == "image"
    assert "[görsel açıklaması yakında]" in chunk.content
    assert chunk.page_number == 1


async def _ingest_doc_with_mixed_pdf(tmp_path: Path, db_session: AsyncSession) -> None:
    """Ortak fixture: 1 metin sayfası (revenue'lu) + 1 tablo sayfası; tümü ingest edilir."""
    pdf = _build_pdf(
        tmp_path / "mixed.pdf",
        [
            Paragraph(
                "Revenue grew 42 percent year over year in the subscription "
                "segment, the strongest quarter in company history.",
                styles["Normal"],
            ),
            PageBreak(),
            Table(
                [["Metric", "Q3 2025", "Q3 2026"], ["Revenue", "1.2M", "1.8M"]],
                colWidths=[100, 80, 80],
                style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]),
            ),
        ],
    )
    doc = await _create_parsed_document(db_session, pdf)  # owner = alice
    summary = await DocumentIngestionService(db_session, ALICE_ID).ingest_document_with_pdf(doc.id)
    assert summary is not None
    assert summary["text_chunks"] >= 1 and summary["table_chunks"] == 1


async def test_search_only_tables(
    tmp_path: Path, db_session: AsyncSession, app_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """chunk_types=["table"] filtresi yalnızca tablo chunk'ları döndürür."""
    await _ingest_doc_with_mixed_pdf(tmp_path, db_session)

    resp = app_client.post(
        HYBRID_URL,
        json={"query": "Revenue", "chunk_types": ["table"], "use_rerank": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results, "tablo sonucu bekleniyor"
    assert all(r["chunk_type"] == "table" for r in results)


async def test_search_mixed(
    tmp_path: Path, db_session: AsyncSession, app_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Filtresiz arama metin ve tablo chunk'larının karışımını döndürür."""
    await _ingest_doc_with_mixed_pdf(tmp_path, db_session)

    resp = app_client.post(
        HYBRID_URL,
        json={"query": "Revenue", "use_rerank": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    types = {r["chunk_type"] for r in resp.json()["results"]}
    assert {"text", "table"} <= types


async def test_search_response_has_metadata(
    tmp_path: Path, db_session: AsyncSession, app_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Arama yanıtında chunk_type ve page_number alanları dolu döner."""
    await _ingest_doc_with_mixed_pdf(tmp_path, db_session)

    resp = app_client.post(
        HYBRID_URL,
        json={"query": "Revenue", "chunk_types": ["table"], "use_rerank": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    top = resp.json()["results"][0]
    assert top["chunk_type"] == "table"
    assert top["page_number"] == 2  # tablo 2. sayfada
    assert "chunk_type" in top and "page_number" in top
