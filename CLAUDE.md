# CLAUDE.md — Fin-RAG

## Project identity
Enterprise **Multi-modal** RAG assistant for **Acme Financial** (financial reporting SaaS).
Built as a real client delivery (Upwork job simulation).

## THE requirement
Financial reports are full of tables, charts, and footnotes. Standard text-based RAG misses them. Fin-RAG MUST extract, index, and retrieve text + tables + images together.

## Client
Acme Financial — see `docs/CLIENT_BRIEF.md` for full brief.
- 500+ page financial PDFs.
- Current RAG fails on "Q3 revenue growth" (table data).
- Needs verifiable citations (page number + bounding box).

## Stack (Base)
- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic
- **AI:** LangGraph, LangChain, Groq (llama-3.2-90b-vision), sentence-transformers (bge-small)
- **DB:** PostgreSQL 16 + pgvector
- **Frontend:** Next.js 14, TypeScript, Tailwind
- **Infra:** Docker Compose

## Stack (New additions for multi-modal)
- **PDF Parsing:** `pdfplumber` (text + tables), `PyMuPDF` (images)
- **Table Extraction:** `camelot-py`
- **VLM:** Groq Vision (or similar) for chart/figure analysis
- **Visual Retrieval:** ColPali / ColQwen (or text-based proxy via OCR)

## Ports & services
| Service | Port | Container |
|---------|------|-----------|
| web | 3003 | multi-web |
| api | 8003 | multi-api |
| postgres | 5435 | multi-postgres |

## Roadmap
- [ ] Faz 0: Fork from support-ai + port/branding
- [ ] Faz 1: PDF Ingestion pipeline (text + tables + images)
- [ ] Faz 2: Multi-modal indexing (tables in DB, images in object storage)
- [ ] Faz 3: VLM integration (chart reading via Groq Vision)
- [ ] Faz 4: Hybrid search update (text + table embeddings)
- [ ] Faz 5: Multi-modal citations (page + bounding box)
- [ ] Faz 6: Frontend PDF viewer with highlight
- [ ] Faz 7: Docs + Demo

## Code rules
- Type hints, `black` + `ruff` (line-length 100)
- DB isolation: tests use `multi_test` DB