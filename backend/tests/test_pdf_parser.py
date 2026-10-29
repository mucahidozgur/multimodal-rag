"""PDFParser birim + endpoint testleri.

Örnek PDF'ler reportlab ile runtime'da üretilir (repo'ya test fixture dosyası
konmaz); çıkarılan görseller tmp_path altındaki storage'a yazılır.
"""

from pathlib import Path
from uuid import uuid4

import pytest
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

from app.services.pdf_parser import PDFParser, classify_image

DOCS_URL = "/api/documents"

styles = getSampleStyleSheet()


def _build_pdf(path: Path, story: list) -> Path:
    """Verilen platypus öğelerinden tek sayfalık PDF üretir."""
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    doc.build(story)
    return path


def _make_png(path: Path, size: tuple[int, int] = (200, 150)) -> Path:
    """Test görseli üretir (düz renkli PNG)."""
    img = PILImage.new("RGB", size, (200, 30, 30))
    img.save(path, format="PNG")
    return path


async def test_parse_text_only(tmp_path: Path) -> None:
    """Metin PDF'i: doğru sayfa sayısı ve çıkarılan metin."""
    pdf = _build_pdf(
        tmp_path / "text.pdf",
        [
            Paragraph("Quarterly Report", styles["Title"]),
            Paragraph("Q3 revenue growth reached 42 percent year over year.", styles["Normal"]),
        ],
    )
    result = await PDFParser(storage_dir=tmp_path / "storage").parse_pdf(pdf)

    assert len(result["pages"]) == 1
    page = result["pages"][0]
    assert page["page_number"] == 1
    assert "42 percent" in page["text"]
    assert page["tables"] == []
    assert page["images"] == []


async def test_parse_table(tmp_path: Path) -> None:
    """Tablo PDF'i: 1 tablo çıkar ve markdown hücreleri doğru taşır."""
    table = Table(
        [
            ["Metric", "Q3 2025", "Q3 2026"],
            ["Revenue", "1.2M", "1.8M"],
            ["EBITDA", "0.4M", "0.6M"],
        ],
        colWidths=[100, 80, 80],
        style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]),
    )
    pdf = _build_pdf(tmp_path / "table.pdf", [Paragraph("Financials", styles["Title"]), table])
    result = await PDFParser(storage_dir=tmp_path / "storage").parse_pdf(pdf)

    tables = result["pages"][0]["tables"]
    assert len(tables) == 1
    markdown = tables[0]["markdown"]
    assert "| Metric |" in markdown
    assert "| Revenue |" in markdown
    assert "| --- |" in markdown  # ayraç satırı (başlık ile veri arasında)
    assert tables[0]["data"][1][0] == "Revenue"


async def test_parse_image(tmp_path: Path) -> None:
    """Görsel PDF'i: 1 görsel çıkar, diskte dosya oluşur, boyutlar tutar."""
    png = _make_png(tmp_path / "fig.png", size=(200, 150))
    pdf = _build_pdf(tmp_path / "image.pdf", [RLImage(str(png), 200, 150)])
    storage = tmp_path / "storage"
    result = await PDFParser(storage_dir=storage).parse_pdf(pdf)

    images = result["pages"][0]["images"]
    assert len(images) == 1
    image = images[0]
    assert image["width"] == 200
    assert image["height"] == 150
    assert image["type"] == "figure"
    saved = list((storage / "images").glob("*"))
    assert len(saved) == 1  # diskte dosya oluştu


def test_classify_image_heuristic() -> None:
    """Boyut bazlı tip tahmini: chart / logo / figure."""
    assert classify_image(500, 300) == "chart"
    assert classify_image(50, 50) == "logo"
    assert classify_image(200, 150) == "figure"


def test_parse_pdf_api(
    app_client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /{id}/parse-pdf: auth zorunlu, başarılı yanıt, idempotent, 400/404."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))

    png = _make_png(tmp_path / "fig.png", size=(500, 300))
    table = Table(
        [["Item", "Value"], ["Cash", "100M"]],
        colWidths=[100, 80],
        style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]),
    )
    # 2 sayfa: görsel 1. sayfada, tablo 2. sayfada (ayrı ayrı tespit edilir)
    pdf = _build_pdf(
        tmp_path / "api.pdf",
        [Paragraph("Form 10-K", styles["Title"]), RLImage(str(png), 500, 300), PageBreak(), table],
    )

    # Doküman oluştur (file_path PDF'i gösterir)
    resp = app_client.post(
        DOCS_URL,
        json={"title": "10-K", "content": "Annual report", "file_path": str(pdf)},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    # Token'sız reddedilir
    anon = app_client.post(f"{DOCS_URL}/{doc_id}/parse-pdf")
    assert anon.status_code in (401, 403)

    # Başarılı parse
    parsed = app_client.post(f"{DOCS_URL}/{doc_id}/parse-pdf", headers=auth_headers)
    assert parsed.status_code == 200
    body = parsed.json()
    assert body == {"pages_parsed": 2, "tables_found": 1, "images_found": 1}
    assert list((tmp_path / "storage" / "images").glob("*"))  # görsel diske yazıldı

    # İdempotent: ikinci parse aynı özeti döner (eski kayıtlar silinir)
    again = app_client.post(f"{DOCS_URL}/{doc_id}/parse-pdf", headers=auth_headers)
    assert again.status_code == 200
    assert again.json() == body

    # file_path olmayan doküman → 400
    no_file = app_client.post(
        DOCS_URL, json={"title": "no pdf", "content": "text"}, headers=auth_headers
    )
    bad = app_client.post(f"{DOCS_URL}/{no_file.json()['id']}/parse-pdf", headers=auth_headers)
    assert bad.status_code == 400

    # Olmayan doküman → 404
    missing = app_client.post(f"{DOCS_URL}/{uuid4()}/parse-pdf", headers=auth_headers)
    assert missing.status_code == 404
