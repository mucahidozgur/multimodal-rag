"""Document CRUD endpoint'leri."""

from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import BASE_DIR, get_settings
from app.core.db import get_db
from app.models.document import Document
from app.schemas.ai import IndexResponse
from app.schemas.auth import UserInfo
from app.schemas.document import (
    DocumentCreate,
    DocumentListItem,
    DocumentListResponse,
    DocumentRead,
    DocumentUpdate,
    ParsePdfResponse,
    ReindexImagesResponse,
)
from app.services.document import DocumentService
from app.services.ingestion import DocumentIngestionService
from app.services.pdf_parser import PDFIngestionService

router = APIRouter(prefix="/api/documents", tags=["documents"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
UserDep = Annotated[UserInfo, Depends(get_current_user)]


@router.post("", response_model=DocumentRead, status_code=201)
async def create_document(body: DocumentCreate, db: DbDep, current_user: UserDep) -> Document:
    """Yeni doküman oluşturur."""
    service = DocumentService(db, UUID(current_user.id))
    return await service.create(body)


@router.post("/upload", response_model=DocumentRead, status_code=201)
async def upload_document_pdf(
    file: Annotated[UploadFile, File(...)],
    db: DbDep,
    current_user: UserDep,
    title: Annotated[str | None, Form()] = None,
) -> Document:
    """PDF dosyası yükler: storage/pdfs/{uuid}.pdf'e kaydeder, doküman oluşturur.

    Faz 5: tarayıcıdan PDF yükleme akışının ilk adımı; index'leme ayrıca
    POST /{id}/index ile yapılır.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    pdfs_dir = Path(get_settings().STORAGE_DIR) / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    stored = pdfs_dir / f"{uuid4().hex}.pdf"
    stored.write_bytes(await file.read())

    doc_title = (title or Path(filename).stem or "document.pdf").strip()
    doc = await DocumentService(db, UUID(current_user.id)).create(
        DocumentCreate(title=doc_title, content="", file_path=str(stored))
    )
    return doc


@router.get("/{document_id}/file")
async def get_document_file(document_id: UUID, db: DbDep, current_user: UserDep) -> FileResponse:
    """Dokümanın PDF dosyasını stream eder (yalnızca sahibi erişebilir).

    Faz 5: frontend PDF viewer buradan okur (sayfa render + bbox highlight).
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(doc.owner_id) != current_user.id:
        raise HTTPException(status_code=403, detail="Not document owner")
    if not doc.file_path:
        raise HTTPException(status_code=404, detail="Document has no file_path")
    path = Path(doc.file_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(path, media_type="application/pdf", filename=f"{doc.title}.pdf")


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    db: DbDep,
    current_user: UserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    """Kullanıcının dokümanlarını sayfalar halinde listeler."""
    service = DocumentService(db, UUID(current_user.id))
    docs, total = await service.list(limit, offset)
    items = [
        DocumentListItem(
            id=doc.id,
            title=doc.title,
            source=doc.source,
            file_path=doc.file_path,
            created_at=doc.created_at,
            content_preview=doc.content[:200],
        )
        for doc in docs
    ]
    return DocumentListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/{document_id}/index", response_model=IndexResponse)
async def index_document(document_id: UUID, db: DbDep, current_user: UserDep) -> IndexResponse:
    """Dokümanı index'ler.

    file_path doluysa multi-modal akış (parse-pdf + text/table/image chunk'ları);
    değilse geri uyumlu text-only chunking. Yanıt source_type ile hangi akışın
    koştuğunu belirtir.
    """
    owner_id = UUID(current_user.id)
    doc = await DocumentService(db, owner_id).get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    service = DocumentIngestionService(db, owner_id)
    if doc.file_path:
        try:
            result = await service.ingest_document_with_pdf(document_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return IndexResponse(document_id=document_id, source_type="pdf", **result)

    result = await service.index_document(document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    # result zaten document_id içerir.
    return IndexResponse(source_type="text", **result)


@router.post("/{document_id}/parse-pdf", response_model=ParsePdfResponse)
async def parse_document_pdf(
    document_id: UUID, db: DbDep, current_user: UserDep
) -> ParsePdfResponse:
    """Dokümanın PDF dosyasını ayrıştırır: sayfa, tablo ve görselleri kaydeder.

    Dosya yolu Document.file_path alanından okunur; ayrıştırma idempotenttir
    (önceki PDFPage/PDFTable/PDFImage kayıtları silinir).
    """
    doc = await DocumentService(db, UUID(current_user.id)).get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path:
        raise HTTPException(status_code=400, detail="Document has no file_path")
    try:
        result = await PDFIngestionService(db).parse_document(doc)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ParsePdfResponse(**result)


@router.post("/{document_id}/reindex-images", response_model=ReindexImagesResponse)
async def reindex_document_images(
    document_id: UUID, db: DbDep, current_user: UserDep
) -> ReindexImagesResponse:
    """Dokümanın image chunk'larını Vision ile yeniden açıklar (backfill).

    Faz 3 öncesi placeholder'la indexlenmiş görseller için: her image chunk
    Vision'dan gerçek açıklamayla güncellenir (content + embedding).
    """
    updated = await DocumentIngestionService(db, UUID(current_user.id)).reindex_images(document_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return ReindexImagesResponse(updated=updated)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: UUID, db: DbDep, current_user: UserDep) -> Document:
    """Tek dokümanı döndürür; yoksa 404."""
    doc = await DocumentService(db, UUID(current_user.id)).get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.put("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: UUID, body: DocumentUpdate, db: DbDep, current_user: UserDep
) -> Document:
    """Dokümanı günceller; yoksa 404."""
    doc = await DocumentService(db, UUID(current_user.id)).update(document_id, body)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: UUID, db: DbDep, current_user: UserDep) -> None:
    """Dokümanı siler; yoksa 404."""
    deleted = await DocumentService(db, UUID(current_user.id)).delete(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
