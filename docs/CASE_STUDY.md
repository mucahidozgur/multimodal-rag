# Case Study: Multi-Modal RAG for Financial Reports

## The Problem

"Financial reports are 500+ pages of text, tables, and charts. Our text-only RAG
fails on roughly 70% of analyst queries. 'What was Q3 revenue growth?' lives in a
table. 'What does the EBITDA chart show?' lives in an image. Neither exists in
plain text — so neither is retrievable."

This was the brief from a financial-reporting SaaS client. Their existing
text-based retrieval assistant could quote paragraphs but went silent on
anything tabular or visual: the exact questions analysts ask most. On top of
that, every answer had to be verifiable — citations pointing to the precise
location on the precise page, because compliance teams check everything.

## The Solution

I designed and delivered **Fin-RAG**, an enterprise multi-modal RAG system that
treats a PDF as three separate modalities — **text, tables, images** — indexes
each one in its own vector space, and fuses them into a single search surface.

**Pipeline.** A PDF ingestion service splits every page with pdfplumber
(text + tables, each with bounding boxes) and PyMuPDF (embedded images,
extracted to disk with coordinates). Indexing writes three chunk types:
`text` chunks from page content, `table` chunks from markdown-rendered tables
(prefixed with `Page N — Table i` for context), and `image` chunks whose content
is a *VLM-generated description*. Retrieval is hybrid — pgvector cosine
similarity fused with PostgreSQL BM25 full-text via Reciprocal Rank Fusion —
with an optional `chunk_types` filter so a query can target only tables or only
charts. A cross-encoder reranks candidates, a citation-verification step binds
every sentence of the answer to a source chunk, and a hallucination detector
scores faithfulness. Every retrieved chunk carries `page_number` and `bbox`
`[x0, top, x1, bottom]`.

**Frontend.** A Next.js app where analysts drag-and-drop a PDF (with staged
progress: upload → parse → index), chat in natural language, and click any
citation chip to open the PDF viewer at the exact page — with the supporting
table or chart highlighted by a yellow overlay computed from the stored bbox,
scaled from PDF points (72dpi) to the rendered viewport.

## What I Built

- **Backend (FastAPI, Python 3.11):** async SQLAlchemy 2.0 + PostgreSQL 16 /
  pgvector; alembic migrations; endpoints for upload, file streaming,
  multi-modal indexing, filtered hybrid search, image re-indexing (backfill),
  SSE streaming chat with verification events, RAGAS evaluation, and analytics.
- **AI pipeline:** Groq LLM for chat, Groq Vision (llama-4-scout) for chart
  reading with per-type prompts and graceful fallbacks, local sentence-transformers
  embeddings (bge-small), cross-encoder reranking, hierarchical chunking,
  self-critique corrective RAG, and a LangGraph agent router.
- **Frontend (Next.js 14 + TypeScript + Tailwind):** PDF upload with drag &
  drop, react-pdf viewer with page navigation and bbox highlighting, clickable
  citation chips, document management, and an admin KPI dashboard.
- **Quality & ops:** 129 automated tests (unit + API, real PDFs generated with
  reportlab, all external LLM/VLM calls mocked), black + ruff linting, GitHub
  Actions CI (backend tests against a pgvector service + frontend build), Docker
  Compose, optional Langfuse observability.

## Technical Challenges

**1. Table extraction accuracy.** I compared pdfplumber, camelot, and
unstructured on real financial tables. Camelot's lattice mode is powerful but
slow and Ghostscript-dependent; unstructured was overkill for this stack.
pdfplumber's line-based strategy detected reportlab and 10-K grid tables
deterministically and — critically — `find_tables()` returns each table's
bounding box natively, which the citation feature required. I kept camelot as
a dependency for future borderless-table cases and documented the trade-off.

**2. Groq Vision model deprecation.** Mid-build, the originally configured
vision model (`llama-3.2-90b-vision-preview`) disappeared from Groq's lineup.
I verified the current offering (`meta-llama/llama-4-scout-17b-16e-instruct`),
made the model a settings field, lazy-loaded the vision client so a missing
package or empty API key never crashes the app, and gave every image chunk a
fallback placeholder that a `reindex-images` backfill endpoint can refresh
later. The pipeline degrades gracefully instead of failing.

**3. bbox coordinate transformation.** PDFs express coordinates in points
(72dpi) with a top-left origin; the browser renders pages at arbitrary scale.
Storing raw PDF bboxes in the chunk metadata and computing
`scale = renderedWidth / pageWidth` at display time kept the backend
renderer-agnostic — the same bbox works for any future client. I also caught
(and fixed) a subtle UUID-vs-string bug in citation verification that silently
marked every sentence as unsupported in production flows.

## Results

- **129 passing tests** across 6 delivery phases (fork → parsing → indexing →
  VLM → citations → frontend), CI-green.
- Multi-modal retrieval working end-to-end: *"Q3 revenue"* returns the table
  chunk with page + bbox; chart questions return VLM-generated descriptions.
- Every answer carries verifiable, pixel-precise citations — the client's core
  requirement.

## How I'd Apply This to Your Project

The same architecture transfers directly: any long-document domain where
answers hide in structured artifacts — legal contracts (clause tables),
medical records (lab panels), engineering specs (diagrams). I'd start by
running your top-100 failed queries through the three chunk-type filters to
quantify what text-only search is missing, then ship the parsing and indexing
pipeline first (it's independent of any LLM choice), wire the vision step for
chart-heavy pages, and only then invest in reranking and citation UI tuned to
how your reviewers actually verify sources.
