"""Faz 5 backend testleri: PDF serving + upload + pdf/text index ayrımı."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, PDFPage
from app.services.pdf_parser import PDFIngestionService

DOCS_URL = "/api/documents"


class _FakeVision:
    async def ainvoke(self, messages: list) -> AIMessage:
        return AIMessage(content="Chart description.")


def _make_pdf(path: Path) -> Path:
    """Tek sayfalık metin+tablo PDF üretir."""
    table = Table(
        [["Metric", "Q3 2026"], ["Revenue", "1.8M"]],
        colWidths=[100, 80],
        style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]),
    )
    SimpleDocTemplate(str(path), pagesize=letter).build(
        [Paragraph("Quarterly report.", getSampleStyleSheet()["Normal"]), table]
    )
    return path


def _create_doc(app_client: TestClient, headers: dict[str, str], **extra) -> dict:
    body = {"title": "doc", "content": "text content"}
    body.update(extra)
    resp = app_client.post(DOCS_URL, json=body, headers=headers)
    assert resp.status_code == 201
    return resp.json()


def test_document_file_endpoint(
    app_client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """GET /file: auth zorunlu, sahibi 200 alır, diğerleri 403/404."""
    pdf = _make_pdf(tmp_path / "report.pdf")
    created = _create_doc(app_client, auth_headers, file_path=str(pdf))

    # Başarılı: 200 + application/pdf + dosya içeriği
    resp = app_client.get(f"{DOCS_URL}/{created['id']}/file", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == pdf.read_bytes()

    # Token'sız reddedilir
    anon = app_client.get(f"{DOCS_URL}/{created['id']}/file")
    assert anon.status_code in (401, 403)

    # Sahibi olmayan (bob) → 403
    bob_resp = app_client.post("/api/auth/login", json={"username": "bob", "password": "x"})
    bob = {"Authorization": f"Bearer {bob_resp.json()['access_token']}"}
    forbidden = app_client.get(f"{DOCS_URL}/{created['id']}/file", headers=bob)
    assert forbidden.status_code == 403

    # file_path olmayan doküman → 404
    text_doc = _create_doc(app_client, auth_headers)
    no_file = app_client.get(f"{DOCS_URL}/{text_doc['id']}/file", headers=auth_headers)
    assert no_file.status_code == 404

    # Olmayan doküman → 404
    missing = app_client.get(f"{DOCS_URL}/{uuid4()}/file", headers=auth_headers)
    assert missing.status_code == 404


def test_upload_endpoint(
    app_client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /upload: PDF kaydedilir, doküman file_path ile oluşturulur."""
    settings = get_settings()
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))

    pdf = _make_pdf(tmp_path / "finreport.pdf")
    resp = app_client.post(
        f"{DOCS_URL}/upload",
        files={"file": ("finreport.pdf", pdf.read_bytes(), "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "finreport"
    assert body["file_path"]
    stored = Path(body["file_path"])
    assert stored.is_file() and stored.read_bytes() == pdf.read_bytes()

    # PDF olmayan dosya reddedilir
    bad = app_client.post(
        f"{DOCS_URL}/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert bad.status_code == 400

    # Token'sız reddedilir
    anon = app_client.post(
        f"{DOCS_URL}/upload",
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert anon.status_code in (401, 403)


def test_uploaded_pdf_served_from_db_after_disk_loss(
    app_client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload: baytlar DB'ye de yazılır; disk silinse bile /file DB'den servis eder."""
    settings = get_settings()
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))

    pdf = _make_pdf(tmp_path / "fin.pdf")
    resp = app_client.post(
        f"{DOCS_URL}/upload",
        files={"file": ("fin.pdf", pdf.read_bytes(), "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    stored = Path(body["file_path"])
    assert stored.is_file()
    stored.unlink()  # Render restart senaryosu: geçici disk silindi

    served = app_client.get(f"{DOCS_URL}/{body['id']}/file", headers=auth_headers)
    assert served.status_code == 200
    assert served.headers["content-type"] == "application/pdf"
    assert served.content == pdf.read_bytes()


async def test_parse_restores_pdf_from_db(tmp_path: Path, db_session: AsyncSession) -> None:
    """Diskteki PDF kayıpsa parse, DB kopyasından dosyayı geri yazar."""
    pdf = _make_pdf(tmp_path / "src.pdf")
    data = pdf.read_bytes()
    target = tmp_path / "restored" / "doc.pdf"  # var olmayan hedef yol
    doc = Document(
        title="restore-test", content="", owner_id=uuid4(), file_path=str(target), file_data=data
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    await PDFIngestionService(db_session).parse_document(doc)

    assert target.is_file() and target.read_bytes() == data
    pages = list(
        (await db_session.scalars(select(PDFPage).where(PDFPage.document_id == doc.id))).all()
    )
    assert len(pages) >= 1


def test_index_endpoint_pdf_vs_text(
    app_client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """index: file_path yoksa text-only; varsa multi-modal (pdf) akışı koşar."""
    monkeypatch.setattr("app.services.vision.get_vision_llm", lambda: _FakeVision())

    # Text-only (geri uyumlu)
    text_doc = _create_doc(
        app_client, auth_headers, title="text doc", content="Uzun metin içeriği. " * 40
    )
    text_resp = app_client.post(f"{DOCS_URL}/{text_doc['id']}/index", headers=auth_headers)
    assert text_resp.status_code == 200
    assert text_resp.json()["source_type"] == "text"
    assert text_resp.json()["chunks_created"] >= 1

    # PDF (multi-modal)
    pdf = _make_pdf(tmp_path / "report.pdf")
    pdf_doc = _create_doc(app_client, auth_headers, title="pdf doc", file_path=str(pdf))
    pdf_resp = app_client.post(f"{DOCS_URL}/{pdf_doc['id']}/index", headers=auth_headers)
    assert pdf_resp.status_code == 200
    body = pdf_resp.json()
    assert body["source_type"] == "pdf"
    assert body["text_chunks"] >= 1
    assert body["table_chunks"] == 1
    assert body["image_chunks"] == 0
