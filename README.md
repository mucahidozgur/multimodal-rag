# Fin-RAG — Multi-modal RAG for Financial Reports

Enterprise **multi-modal RAG** assistant built for **Acme Financial**. It extracts
**text, tables, and images** from 500+ page PDFs (10-K, 10-Q), indexes each
modality separately, reads charts with a Vision model, and cites every answer
with **page number + bounding box** highlight in a PDF viewer.

## The problem

Standard RAG embeds text only. But financial reports store their answers in
tables ("Q3 revenue growth") and charts ("EBITDA trend"). Text-only RAG says
"I don't know" or hallucinates. Fin-RAG retrieves all three.

## Features

| Faz | Özellik |
|-----|---------|
| 0 | support-ai fork + marka/port taşıması |
| 1 | **PDF Ingestion:** pdfplumber (text + tables) + PyMuPDF (images), tablo → markdown |
| 2 | **Multi-modal Indexing:** `text` / `table` / `image` chunk tipleri, ayrı ayrı embed, `chunk_types` filtreli hibrit arama |
| 3 | **VLM Chart Reading:** Groq Vision (llama-4-scout) ile grafik açıklamaları + `reindex-images` backfill |
| 4 | **Citations:** `page_number` + `bbox` `[x0, top, x1, bottom]` tüm chunk'larda; verification `sources` metadata'sı |
| 5 | **PDF UX:** drag & drop upload (progress: yükle → parse → index), react-pdf viewer, citation'a tıkla → sayfa + **bbox highlight** |
| 6 | Docs (ARCHITECTURE, EVALUATION, DEMO_SCRIPT, CASE_STUDY) + GitHub CI |

Anti-hallucination: citation verification (her cümle → kaynak chunk),
faithfulness skoru, RAGAS değerlendirmesi, corrective RAG ve yetersiz bağlamda
LLM'i hiç çağırmayan güven eşiği.

## Stack

| Katman | Teknolojiler |
|--------|-------------|
| Backend | Python 3.11 · FastAPI · SQLAlchemy 2.0 async · Alembic · PostgreSQL 16 + pgvector |
| AI | LangGraph · LangChain · Groq (qwen3.8-27b + llama-4-scout Vision) · sentence-transformers (bge-small) · cross-encoder reranker (bge-reranker-v2-m3) · RAGAS |
| PDF | **pdfplumber** (text + tables + bbox) · **PyMuPDF** (images + bbox) · camelot-py (yedek) |
| Frontend | Next.js 14 · TypeScript · Tailwind · **react-pdf** (viewer + highlight) |
| Infra | Docker Compose · GitHub Actions CI · Langfuse (opsiyonel) |

## Architecture

```
PDF Upload → PDFParser (pdfplumber + PyMuPDF + bbox)
          → 3 chunk tipi (text | table | image) — ayrı ayrı embed
          → image chunk = VLM açıklaması (Groq Vision)
Hybrid Search: pgvector cosine + BM25 (PostgreSQL FTS) → RRF → cross-encoder rerank
Chat: Groq LLM → citation verification → SSE (sources → token → verification)
Citations: page_number + bbox → PDFViewer highlight (72dpi → viewport ölçeği)
```

Ayrıntılı mimari: [ARCHITECTURE.md](ARCHITECTURE.md)

## Multi-modal

Bir PDF üç modaliteye ayrılır ve her biri kendi chunk tipiyle indexlenir:

- **`text`** — sayfa metni, hiyerarşik chunking, `source_ref_id=PDFPage.id`
- **`table`** — markdown tablo, `"Page N — Table i:"` context başlığıyla embed
- **`image`** — Groq Vision açıklaması (chart/figure/logo prompt'ları);
  VLM hatasında fallback placeholder + `POST /api/documents/{id}/reindex-images`
  ile geri doldurma

Arama tarafında `chunk_types: ["table"]` gibi filtreler hem vektör hem BM25
sorgusuna uygulanır:

```bash
curl -X POST http://localhost:8003/api/ai/search/hybrid \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query": "Q3 revenue growth", "chunk_types": ["table"], "use_rerank": false}'
# → {"chunk_type": "table", "page_number": 1, "bbox": [156, 418, 456, 472], ...}
```

## Citations

Her chunk `page_number` ve `bbox` `[x0, top, x1, bottom]` (PDF nokta birimi)
taşır. Chat'in verification event'i `sources` listesinde bunları döndürür;
frontend citation chip'ine tıklanınca PDFViewer ilgili sayfayı açar ve
koordinatı render ölçeğine oranlayarak **sarı kutu + turuncu çerçeveyle**
vurgular.

```
Chat cevabı → "📄 Acme Q3 — sayfa 1" chip'i → PDFViewer açılır → tablo vurgulanır
```

## Kurulum

```bash
cp .env.example .env          # GROQ_API_KEY doldurun (VLM + LLM için)
docker compose build api
docker compose up -d postgres api
docker compose exec postgres psql -U multi -d multi -c "CREATE DATABASE multi_test OWNER multi;"   # yalnızca testler için
curl http://127.0.0.1:8003/health
# {"status":"ok","service":"fin-rag"}
```

Gerekli env değişkenleri (`.env`):

```
GROQ_API_KEY=                    # zorunlu (LLM + VLM); boşsa fallback çalışır
VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct   # Groq Vision
DATABASE_URL=postgresql+asyncpg://multi:multi@localhost:5435/multi
TEST_DATABASE_URL=postgresql+asyncpg://multi:multi@localhost:5435/multi_test
```

Testler (129):

```bash
cd backend
python -m venv .venv && .venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pytest -v
```

Frontend:

```bash
cd frontend
npm ci && npm run build     # prebuild, pdfjs worker'ını public/'e kopyalar
```

## Demo

5-7 dakikalık senaryo: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
— PDF yükle → tablo sorusu → grafik sorusu → "bilgi yok" cevabı → citation
highlight → admin KPI → Langfuse.

![Demo screenshot placeholder: PDF upload](docs/screenshots/upload.png)
![Demo screenshot placeholder: bbox highlight](docs/screenshots/highlight.png)

## Docs & Evaluation

- [ARCHITECTURE.md](ARCHITECTURE.md) — mimari + karar notları
- [docs/EVALUATION.md](docs/EVALUATION.md) — RAGAS metrikleri + multi-modal ölçüm
- [docs/CASE_STUDY.md](docs/CASE_STUDY.md) — teslim case study
- [docs/CLIENT_BRIEF.md](docs/CLIENT_BRIEF.md) — müşteri brief'i

## Roadmap

- [x] Faz 0: Fork from support-ai + port/branding
- [x] Faz 1: PDF Ingestion pipeline (text + tables + images)
- [x] Faz 2: Multi-modal indexing + filtered hybrid search
- [x] Faz 3: VLM integration (chart reading)
- [x] Faz 4: Multi-modal citations (page + bbox)
- [x] Faz 5: Frontend PDF viewer + multi-modal upload
- [x] Faz 6: Docs + demo + CI
