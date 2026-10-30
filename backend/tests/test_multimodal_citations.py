"""Faz 4 multi-modal citation testleri: bbox çıkarımı, saklanması ve dönüşü."""

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Image as RLImage,
)
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import deterministic_user_id
from app.models.document import Chunk, Document
from app.services.ingestion import DocumentIngestionService
from app.services.pdf_parser import PDFIngestionService, PDFParser

HYBRID_URL = "/api/ai/search/hybrid"
ALICE_ID = UUID(deterministic_user_id("alice"))

styles = getSampleStyleSheet()


class _FakeVision:
    """Vision LLM'i: bbox ile ilgisi yok; ingest'i gerçek ağ olmadan çalıştırır."""

    async def ainvoke(self, messages: list) -> AIMessage:
        return AIMessage(content="Bar chart description.")


def _build_citation_pdf(path: Path) -> Path:
    """1 sayfa: metin + görsel + tablo (hepsi bbox taşır)."""
    png = path.with_suffix(".png")
    PILImage.new("RGB", (400, 250), (30, 120, 220)).save(png)
    table = Table(
        [["Metric", "Q3 2026"], ["Revenue", "1.8M"]],
        colWidths=[100, 80],
        style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]),
    )
    SimpleDocTemplate(str(path), pagesize=letter).build(
        [
            Paragraph("Quarterly revenue report.", styles["Normal"]),
            RLImage(str(png), 400, 250),
            table,
        ]
    )
    return path


async def _create_parsed_document(
    db_session: AsyncSession, pdf_path: Path, owner_id: UUID = ALICE_ID
) -> Document:
    doc = Document(title="citation-doc", content="x", owner_id=owner_id, file_path=str(pdf_path))
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    await PDFIngestionService(db_session).parse_document(doc)
    return doc


async def test_pdf_parser_extracts_bbox(tmp_path: Path) -> None:
    """Parse sonucunda sayfa, tablo ve görsel bbox'ları [x0, top, x1, bottom] dolu."""
    pdf = _build_citation_pdf(tmp_path / "cite.pdf")
    result = await PDFParser(storage_dir=tmp_path / "storage").parse_pdf(pdf)

    page = result["pages"][0]
    assert page["bbox"] and len(page["bbox"]) == 4
    assert page["bbox"][2] > page["bbox"][0]  # x1 > x0
    assert page["bbox"][3] > page["bbox"][1]  # bottom > top

    assert len(page["tables"]) == 1
    table_bbox = page["tables"][0]["bbox"]
    assert len(table_bbox) == 4 and all(isinstance(v, (int, float)) for v in table_bbox)

    assert len(page["images"]) == 1
    image_bbox = page["images"][0]["bbox"]
    assert image_bbox and len(image_bbox) == 4


async def test_ingest_saves_bbox_to_chunk(
    tmp_path: Path, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingest sonrası her chunk tipi bbox taşır."""
    monkeypatch.setattr("app.services.vision.get_vision_llm", lambda: _FakeVision())
    pdf = _build_citation_pdf(tmp_path / "cite.pdf")
    doc = await _create_parsed_document(db_session, pdf, owner_id=uuid4())
    summary = await DocumentIngestionService(db_session, doc.owner_id).ingest_document_with_pdf(
        doc.id
    )
    await db_session.commit()

    assert summary and summary["text_chunks"] >= 1
    assert summary["table_chunks"] == 1 and summary["image_chunks"] == 1

    chunks = list(
        (await db_session.scalars(select(Chunk).where(Chunk.document_id == doc.id))).all()
    )
    for chunk in chunks:
        assert chunk.bbox and len(chunk.bbox) == 4, f"{chunk.chunk_type} chunk bbox boş"
    table_chunk = next(c for c in chunks if c.chunk_type == "table")
    assert table_chunk.page_number == 1


async def test_search_returns_bbox(
    tmp_path: Path,
    db_session: AsyncSession,
    app_client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hybrid search sonuçlarında bbox + page_number döner."""
    monkeypatch.setattr("app.services.vision.get_vision_llm", lambda: _FakeVision())
    pdf = _build_citation_pdf(tmp_path / "cite.pdf")
    doc = await _create_parsed_document(db_session, pdf)
    await DocumentIngestionService(db_session, ALICE_ID).ingest_document_with_pdf(doc.id)
    await db_session.commit()

    resp = app_client.post(
        HYBRID_URL,
        json={"query": "Revenue", "chunk_types": ["table"], "use_rerank": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results
    top = results[0]
    assert top["chunk_type"] == "table"
    assert top["page_number"] == 1
    assert top["bbox"] and len(top["bbox"]) == 4


def test_citation_includes_page_and_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_citations: sources objesi page_number + bbox taşır."""
    from app.services.verification import verify_citations

    class _FakeVerifyLLM:
        def invoke(self, messages, config=None, **kwargs) -> SimpleNamespace:
            return SimpleNamespace(content='{"results": {"0": "chunk-t"}}')

    monkeypatch.setattr("app.services.verification.get_llm", lambda: _FakeVerifyLLM())

    sources = [
        {
            "chunk_id": "chunk-t",
            "content": "Revenue reached 1.8M in Q3 2026.",
            "page_number": 3,
            "bbox": [100.0, 200.0, 400.0, 260.0],
        }
    ]
    result = verify_citations("Revenue reached 1.8M in Q3 2026.", sources)
    assert result["verified"] is True
    assert result["sources"] == [
        {"chunk_id": "chunk-t", "page_number": 3, "bbox": [100.0, 200.0, 400.0, 260.0]}
    ]
    assert result["sentences"][0]["page_number"] == 3
    assert result["sentences"][0]["bbox"] == [100.0, 200.0, 400.0, 260.0]
