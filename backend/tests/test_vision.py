"""Vision servisi + image ingestion + reindex-images endpoint testleri.

Gerçek Groq çağrısı yapılmaz: app.services.vision.get_vision_llm monkeypatch
ile sahte bir vision LLM'e yönlendirilir (prompt yakalanır, hazır cevap döner).
"""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from PIL import Image as PILImage
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Image as RLImage
from reportlab.platypus import SimpleDocTemplate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import deterministic_user_id
from app.models.document import Chunk, Document, PDFImage, PDFPage
from app.services.ingestion import DocumentIngestionService
from app.services.pdf_parser import PDFIngestionService
from app.services.vision import VisionService

DOCS_URL = "/api/documents"
ALICE_ID = UUID(deterministic_user_id("alice"))


class FakeVisionLLM:
    """Sahte vision LLM: son mesajın text bloğunu yakalar, hazır cevap döner."""

    def __init__(self, reply: str = "Bar chart showing revenue growth from 1.2M to 1.8M.") -> None:
        self.reply = reply
        self.last_prompt: str | None = None

    async def ainvoke(self, messages: list) -> AIMessage:
        for block in messages[-1].content:
            if isinstance(block, dict) and block.get("type") == "text":
                self.last_prompt = block["text"]
        return AIMessage(content=self.reply)


class FailingVisionLLM:
    """Vision API çökmesini simüle eder."""

    async def ainvoke(self, messages: list) -> AIMessage:
        raise RuntimeError("Groq API down")


@pytest.fixture
def fake_vision(monkeypatch: pytest.MonkeyPatch) -> FakeVisionLLM:
    """Vision LLM'i sahte başarılı modele yönlendirir."""
    fake = FakeVisionLLM()
    monkeypatch.setattr("app.services.vision.get_vision_llm", lambda: fake)
    return fake


def _make_png(path: Path, size: tuple[int, int] = (400, 250)) -> Path:
    PILImage.new("RGB", size, (30, 120, 220)).save(path)
    return path


def _build_image_pdf(path: Path, png: Path) -> Path:
    SimpleDocTemplate(str(path), pagesize=letter).build([RLImage(str(png), 400, 250)])
    return path


async def _create_parsed_document(
    db_session: AsyncSession, pdf_path: Path, owner_id: UUID
) -> Document:
    doc = Document(title="vision-doc", content="x", owner_id=owner_id, file_path=str(pdf_path))
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    await PDFIngestionService(db_session).parse_document(doc)
    return doc


async def _image_rows(db_session: AsyncSession, document_id: UUID) -> list[PDFImage]:
    return list(
        (
            await db_session.scalars(
                select(PDFImage)
                .join(PDFPage, PDFPage.id == PDFImage.page_id)
                .where(PDFPage.document_id == document_id)
                .options(selectinload(PDFImage.page))
            )
        ).all()
    )


async def test_describe_chart(tmp_path: Path, fake_vision: FakeVisionLLM) -> None:
    """chart tipi için açıklama döner; prompt chart'a özel seçilir."""
    png = _make_png(tmp_path / "chart.png")
    description = await VisionService().describe_image(png, "chart")
    assert description == fake_vision.reply
    assert fake_vision.last_prompt and "chart" in fake_vision.last_prompt.lower()


async def test_describe_figure(tmp_path: Path, fake_vision: FakeVisionLLM) -> None:
    """figure tipi için açıklama döner; prompt figure'a özel seçilir."""
    png = _make_png(tmp_path / "fig.png")
    description = await VisionService().describe_image(png, "figure")
    assert description == fake_vision.reply
    assert fake_vision.last_prompt and "figure" in fake_vision.last_prompt.lower()


async def test_ingest_images_with_vision(
    tmp_path: Path, db_session: AsyncSession, fake_vision: FakeVisionLLM
) -> None:
    """Vision başarılıyken image chunk content'i gerçek açıklama içerir."""
    png = _make_png(tmp_path / "fig.png")
    pdf = _build_image_pdf(tmp_path / "img.pdf", png)
    doc = await _create_parsed_document(db_session, pdf, owner_id=uuid4())
    images = await _image_rows(db_session, doc.id)

    added = await DocumentIngestionService(db_session, doc.owner_id).ingest_images(images)
    await db_session.commit()

    chunks = list(
        (await db_session.scalars(select(Chunk).where(Chunk.document_id == doc.id))).all()
    )
    assert added == len(chunks) == 1
    assert fake_vision.reply in chunks[0].content
    assert "yakında" not in chunks[0].content  # placeholder yok


async def test_ingest_images_vision_failure_fallback(
    tmp_path: Path, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vision hata verirse placeholder fallback yazılır, pipeline çökmez."""
    monkeypatch.setattr("app.services.vision.get_vision_llm", lambda: FailingVisionLLM())
    png = _make_png(tmp_path / "fig.png")
    pdf = _build_image_pdf(tmp_path / "img.pdf", png)
    doc = await _create_parsed_document(db_session, pdf, owner_id=uuid4())
    images = await _image_rows(db_session, doc.id)

    added = await DocumentIngestionService(db_session, doc.owner_id).ingest_images(images)
    await db_session.commit()

    chunks = list(
        (await db_session.scalars(select(Chunk).where(Chunk.document_id == doc.id))).all()
    )
    assert added == len(chunks) == 1
    assert "[görsel açıklaması alınamadı: Groq API down]" in chunks[0].content


async def test_reindex_images_endpoint(
    tmp_path: Path,
    db_session: AsyncSession,
    app_client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reindex-images: placeholder'lı chunk'lar gerçek açıklamayla güncellenir."""
    # 1) Vision başarısızken ingest → placeholder'lı image chunk oluşur.
    monkeypatch.setattr("app.services.vision.get_vision_llm", lambda: FailingVisionLLM())
    png = _make_png(tmp_path / "fig.png")
    pdf = _build_image_pdf(tmp_path / "img.pdf", png)
    doc = await _create_parsed_document(db_session, pdf, owner_id=ALICE_ID)
    images = await _image_rows(db_session, doc.id)
    await DocumentIngestionService(db_session, ALICE_ID).ingest_images(images)
    await db_session.commit()

    # 2) Vision başarılıyken endpoint günceller (content + embedding).
    fake = FakeVisionLLM("Real chart description: revenue +50% YoY.")
    monkeypatch.setattr("app.services.vision.get_vision_llm", lambda: fake)

    resp = app_client.post(f"{DOCS_URL}/{doc.id}/reindex-images", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"updated": 1}

    # Endpoint uygulamanın kendi engine'iyle güncelledi; bu session'ın kimlik
    # haritasına takılmadan güncel kolonu doğrudan oku.
    content = await db_session.scalar(select(Chunk.content).where(Chunk.document_id == doc.id))
    # 400x250 görsel boyut sezgisine göre "chart" tipindedir.
    assert content and content.startswith("Page 1 — chart: Real chart description")

    # 3) Token'sız reddedilir.
    anon = app_client.post(f"{DOCS_URL}/{doc.id}/reindex-images")
    assert anon.status_code in (401, 403)


def test_vision_model_config() -> None:
    """Settings.VISION_MODEL güncel Groq vision modelini taşır."""
    assert get_settings().VISION_MODEL == "meta-llama/llama-4-scout-17b-16e-instruct"
