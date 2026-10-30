# Fin-RAG Mimari Dokümanı

## Genel Bakış

Fin-RAG, **Acme Financial** için geliştirilen kurumsal **multi-modal RAG** asistanıdır.
Finansal raporlar (10-K, 10-Q) 500+ sayfa metin, tablo ve grafik içerir; klasik
text-only RAG bu içeriğin büyük bölümünü göremez — "Q3 revenue growth" gibi
cevabı tabloda olan sorular yanıtsız kalır.

Fin-RAG PDF'i üç modaliteye ayırır — **metin, tablo, görsel** — her birini ayrı
vektör uzayına gömer, hibrit aramada birlikte arar, grafikleri VLM ile okur ve
her cevabı **sayfa numarası + bounding box** ile kaynağına bağlar.

**Çözdüğü problem:** tablo/grafik içeren finansal dokümanlarda doğru, kaynak
gösterilebilir soru-cevap.

## Yüksek Seviye Mimari

```
┌─────────────────────────────┐      ┌──────────────────────────────────────────────┐
│  Frontend (Next.js 14)      │      │  Backend (FastAPI)                           │
│                             │      │                                              │
│  PDFUpload (drag&drop) ─────┼─────▶│  POST /documents/upload      storage/pdfs/   │
│  PDFViewer (react-pdf) ◀────┼──────│  GET  /documents/{id}/file   (FileResponse)  │
│  Chat + tıklanabilir        │      │                                              │
│  citation chip'leri ────────┼─────▶│  POST /documents/{id}/index                  │
│  bbox highlight overlay     │      │       │                                      │
└─────────────────────────────┘      │       ▼                                      │
                                     │  ┌─────────────────────────────────────┐     │
                                     │  │ PDFParser (pdfplumber + PyMuPDF)   │     │
                                     │  │  sayfa → text + bbox               │     │
                                     │  │  tablo → data + markdown + bbox    │     │
                                     │  │  görsel → PNG dosyası + bbox       │     │
                                     │  └───────────────┬─────────────────────┘     │
                                     │                  ▼                           │
                                     │  ┌─────────────────────────────────────┐     │
                                     │  │ Ingestion (3 tip chunk)            │     │
                                     │  │  text   → bge-small embedding      │     │
                                     │  │  table  → markdown embedding       │     │
                                     │  │  image  → VLM açıklaması embedding │     │
                                     │  └───────────────┬─────────────────────┘     │
                                     │                  ▼                           │
                                     │  ┌─────────────────────────────────────┐     │
                                     │  │ Hybrid Search (pgvector + BM25)    │     │
                                     │  │  RRF fusion + chunk_types filtresi │     │
                                     │  │  cross-encoder rerank              │     │
                                     │  └───────────────┬─────────────────────┘     │
                                     │                  ▼                           │
                                     │  ┌─────────────────────────────────────┐     │
                                     │  │ Groq LLM (chat) + verification     │     │
                                     │  │  citation doğrulama + faithfulness │     │
                                     │  │  sources: page_number + bbox       │     │
                                     │  └───────────────┬─────────────────────┘     │
                                     │                  ▼                           │
                                     │  SSE: sources → token → verification → done  │
                                     └──────────────────────────────────────────────┘
                                     ┌──────────────────────────────────────────────┐
                                     │  PostgreSQL 16 + pgvector (BM25: tsvector)   │
                                     │  documents / chunks / pdf_pages /            │
                                     │  pdf_tables / pdf_images / query_logs        │
                                     └──────────────────────────────────────────────┘
                                     ┌──────────────────────────────────────────────┐
                                     │  Groq (qwen3.8-27b + llama-4-scout vision)   │
                                     │  + Langfuse observability (opsiyonel)        │
                                     └──────────────────────────────────────────────┘
```

## Katmanlar

| Katman | Bileşenler | Sorumluluk |
|--------|-----------|------------|
| **Frontend** | `src/app` (login, dashboard, assistant, admin), `src/components` (PDFUpload, PDFViewer, MessageBubble, DocumentCard...) | PDF yükleme, chat arayüzü, PDF viewer + bbox highlight, admin KPI'ları |
| **API** | `app/api/` (auth, documents, ai, analytics) | HTTP katmanı: CRUD, upload, file stream, search, SSE chat |
| **Services** | `pdf_parser`, `ingestion`, `rag`, `vision`, `verification`, `chat`, `document`, `chunking`, `evaluation`, `agent`, `critique` | İş mantığı: parse, index, arama, VLM, doğrulama |
| **Models** | `Document`, `Chunk`, `PDFPage`, `PDFTable`, `PDFImage`, `QueryLog` | ORM (SQLAlchemy 2.0 async, UUID PK, JSON bbox) |
| **Core** | `config`, `db`, `llm`, `security`, `observability` | Ayarlar, async engine, LLM/embedding fabrikaları, JWT, Langfuse |

## Multi-modal RAG Pipeline

1. **Ingestion** — PDF, `PDFParser.parse_pdf()` ile ayrıştırılır: `pdfplumber`
   metin + tabloları (bbox'larıyla), `PyMuPDF` gömülü görselleri çıkarır
   (`storage/images/`). Sonuç: `pdf_pages` + `pdf_tables` + `pdf_images` satırları.
2. **Indexing** — `ingest_document_with_pdf()` her modaliteyi ayrı chunk olarak
   embed eder: `text` (sayfa metni, hiyerarşik chunking), `table` (markdown,
   `Page N — Table i:` başlığıyla), `image` (VLM açıklaması). `chunk_type`,
   `source_ref_id`, `page_number`, `bbox` metadata olarak saklanır.
3. **VLM** — `VisionService` görselleri base64 data-URL olarak Groq Vision'a
   (llama-4-scout) gönderir; tip bazlı prompt'la (chart/figure/logo) açıklama
   üretir. Hata durumunda fallback placeholder — pipeline asla çökmez;
   `reindex-images` endpoint'i ile sonradan geri doldurulur.
4. **Retrieval** — `search_hybrid`: vektör (pgvector cosine) + BM25
   (PostgreSQL FTS, `tsv_content` generated column) → RRF fusion.
   `chunk_types=["table"]` filtresi iki tarafta da uygulanır.
5. **Reranking** — cross-encoder (`bge-reranker-v2-m3`) adayları
   (query, content) çiftleriyle yeniden sıralar; `expand_context` ile parent
   retrieval (aynı başlık altındaki chunk'lar).
6. **Anti-hallucination** — `verify_citations` her cümleyi kaynağa bağlar
   (LLM chunk_id döner, uydurma id'ler NONE sayılır); `detect_hallucination`
   faithfulness skorlar. RAGAS metrikleri ile sürekli değerlendirme
   (`/api/ai/evaluate/*`).
7. **Citations** — her chunk `page_number` + `bbox` `[x0, top, x1, bottom]`
   taşır. Frontend citation chip'ine tıklayınca PDFViewer ilgili sayfayı açıp
   koordinatı render ölçeğine oranlayarak sarı kutucukla vurgular.

## Karar Notları

| Karar | Neden |
|-------|-------|
| **pdfplumber + PyMuPDF** (camelot değil) | pdfplumber çizgi çizilmiş tabloları hızlı ve deterministik bulur (`find_tables` bbox verir); PyMuPDF gömülü görselleri `extract_image` + `get_image_bbox` ile birebir çıkarır. camelot (lattice) daha yavaştır ve Ghostscript'e bağımlıdır — kenarlıksız tablolar gerekirse Faz sonrası eklenebilir. |
| **Groq Vision (llama-4-scout)** | Hızlı ve ucuz hosted VLM. `llama-3.2-90b-vision-preview` Groq'ta deprecate edildi; güncel model adı doğrulandı ve `VISION_MODEL` config üzerinden değiştirilebilir. |
| **bbox neden önemli** | Müşteri şartı: "Citation must point to the exact page". Sayfa yetmez — 500 sayfalık raporda tablonun/grafiğin sayfadaki YERİ gerekir. bbox `[x0, top, x1, bottom]` PDF nokta birimiyle (72dpi) saklanır; frontend render genişliğine oranlar. |
| **3 ayrı chunk tipi** | Metin, tablo ve görselin semantik yapısı farklıdır; tek tip embedding "Q3 revenue" sorusunu tablodan bulamaz. `chunk_type` filtreli hibrit arama modaliteler arası ağırlığı yönetmeyi sağlar. |
| **RRF + BM25 + vector** | Vektör anlamı, BM25 anahtar kelimeyi (sayılar, ticker'lar) yakalar; RRF ikisini parametresiz birleştirir. |
| **Lazy VLM/reranker yükleme** | ~2GB'lık reranker ve paket bağımlılıkları uygulama açılışını yavaşlatmasın; ilk kullanımda yüklenir, hatalar çağrı yerinde yakalanır. |
| **Alembic + elle düzeltilen autogenerate** | `ix_chunks_tsv_content` (BM25) index'i metadata'da tanımlı değil; autogenerate her migration'da silmek ister — üç migration'da da elle korundu. |

## Klasör Yapısı

```
multimodal-rag/
├── backend/
│   ├── alembic/                  # migration'lar (4 tablo + chunk metadata)
│   ├── app/
│   │   ├── api/                  # auth, documents, ai, analytics
│   │   ├── core/                 # config, db, llm, security, observability
│   │   ├── models/               # Document, Chunk, PDFPage, PDFTable, PDFImage
│   │   ├── schemas/              # Pydantic modelleri
│   │   └── services/             # pdf_parser, ingestion, rag, vision,
│   │                             # verification, chat, chunking, evaluation
│   ├── scripts/                  # seed_data, run_evaluation
│   ├── storage/                  # PDF'ler + çıkarılan görseller (gitignored)
│   └── tests/                    # 129 test
├── frontend/
│   ├── src/app/                  # login, dashboard, assistant, admin
│   ├── src/components/           # PDFUpload, PDFViewer, MessageBubble...
│   └── scripts/                  # copy-pdf-worker.js (prebuild)
├── docs/                         # CLIENT_BRIEF, EVALUATION, DEMO_SCRIPT, CASE_STUDY
├── scripts/                      # init-db.sh (postgres volume init)
├── docker-compose.yml            # postgres 5435 · api 8003 · web 3003
└── .github/workflows/test.yml    # CI: backend test + lint, frontend build
```
