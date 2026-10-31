"""Doküman ile ilgili Pydantic modelleri."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreate(BaseModel):
    """Yeni doküman girdisi."""

    title: str = Field(min_length=1, max_length=255)
    # Faz 5: PDF dokümanlarında içerik boş olabilir (içerik parse ile gelir).
    content: str = Field(default="", max_length=1_000_000)
    source: str = Field(default="upload", max_length=100)
    file_path: str | None = None  # Faz 1: PDF parse için disk yolu
    # Faz 7: PDF baytlarının DB kopyası (DocumentRead/ListItem'te tanımsız —
    # API yanıtlarında asla dönmez).
    file_data: bytes | None = None


class DocumentUpdate(BaseModel):
    """Güncellenebilir alanlar; source güncellenemez."""

    title: str | None = None
    content: str | None = None
    file_path: str | None = None


class DocumentRead(BaseModel):
    """Dokümanın tam gösterimi."""

    id: UUID
    title: str
    content: str
    owner_id: UUID
    source: str
    file_path: str | None = None
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class DocumentListItem(BaseModel):
    """Liste görünümü: içerik yerine kısa önizleme."""

    id: UUID
    title: str
    source: str
    # Faz 5: PDF varsa "Görüntüle" butonunu açmak için gerekli.
    file_path: str | None = None
    created_at: datetime
    content_preview: str  # ilk 200 karakter

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    """Sayfalanmış liste yanıtı."""

    items: list[DocumentListItem]
    total: int
    limit: int
    offset: int


class ParsePdfResponse(BaseModel):
    """parse-pdf endpoint özeti: kaç sayfa/tablo/görsel işlendi."""

    pages_parsed: int
    tables_found: int
    images_found: int


class ReindexImagesResponse(BaseModel):
    """reindex-images endpoint özeti: kaç image chunk güncellendi."""

    updated: int
