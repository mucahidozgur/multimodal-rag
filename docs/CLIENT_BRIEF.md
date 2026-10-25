
#### Dosya 3: `D:\GravityAntiUygulamalar\multimodal-rag\docs\CLIENT_BRIEF.md`
```markdown
# Client Brief — Acme Financial Multi-modal RAG

**Client:** Acme Financial
**Industry:** Financial Reporting SaaS
**Engagement:** Hourly, 3-4 weeks

## The problem
Acme's users upload 10-K and 10-Q reports (500+ pages). The current RAG assistant searches text fine, but:
1. Tables are invisible. (e.g. "What was Q3 revenue?" fails).
2. Charts are invisible. (e.g. "What did the 2025 EBITDA chart show?").
3. Citations lack page numbers.

## Required features
1. **PDF Upload & Parsing:** Extract text, tables, and images separately.
2. **Table Embedding:** Convert tables to markdown, embed them.
3. **VLM Chart Reading:** Pass images to Groq Vision, store the description.
4. **Hybrid Retrieval:** Search across text + tables + image descriptions.
5. **Multi-modal Citation:** Return (page_number, bounding_box) for verification.
6. **Frontend Viewer:** Open PDF, highlight the source of the answer.

## Success criteria
- Answer questions that require reading a table (e.g. Q3 revenue).
- Answer questions that require reading a chart.
- Citation must point to the exact page.