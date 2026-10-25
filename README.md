# Fin-RAG (Multi-modal)

Enterprise Multi-modal RAG assistant for financial reports.

Built for **Acme Financial** — extracts text, tables, and images from 500+ page PDFs,
retrieves the right data (even from charts), and cites page numbers.

## The problem
Standard RAG embeds text. But financial reports have Q3 revenue tables,
EBITDA charts, and footnotes. Text-only RAG hallucinates or says "I don't know".

## Features
- 📄 **PDF Ingestion:** Text + Tables + Images (pdfplumber, PyMuPDF)
- 🔍 **Hybrid Search:** BM25 + Vector + RRF (inherited from support-ai)
- 🎯 **Reranking:** Cross-encoder (bge-reranker)
- 👁️ **Vision Model:** Groq Vision for reading charts/figures
- 🛡️ **Anti-hallucination:** Citation verification + RAGAS evaluation
- 📊 **Admin Dashboard:** Observability (Langfuse)

## Quick start
```bash
cp .env.example .env
docker compose build api
docker compose up -d postgres api
curl http://127.0.0.1:8003/health