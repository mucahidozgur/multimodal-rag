# Fin-RAG Değerlendirme Rehberi

RAG kalitesi iki katmanda ölçülür: (1) RAGAS metrikleri ile uçtan uca
cevap kalitesi, (2) multi-modal retrieval doğruluğu (chunk tipi bazında).

## 1) RAGAS Metrikleri

| Metrik | Hedef | Ne ölçer |
|--------|-------|----------|
| `faithfulness` | ≥ 0.85 | Cevap, retrieval edilen bağlama ne kadar sadık (hallucination tersi) |
| `answer_relevancy` | ≥ 0.80 | Cevabın soruyla ilgisi |
| `context_precision` | ≥ 0.75 | Dönen bağlamda ilgisiz chunk oranı |

Endpoint'ler:

- `POST /api/ai/evaluate/generate-set` — dokümandan LLM ile sentetik soru-cevap üretir
- `POST /api/ai/evaluate/run` — test setini RAGAS ile değerlendirir

## 2) Multi-modal Ölçüm: Chunk Tipi Doğruluğu

Text-only RAG'in "Q3 revenue growth" gibi soruları kaçırma nedenini ölçmek için
aynı sorgu setini üç filtreyle koşun ve sonuçları karşılaştırın:

```bash
# Yalnızca tablo chunk'ları
curl -X POST http://localhost:8003/api/ai/search/hybrid \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query": "Q3 revenue growth", "chunk_types": ["table"], "use_rerank": false}'

# Yalnızca metin chunk'ları
curl ... -d '{"query": "Q3 revenue growth", "chunk_types": ["text"], "use_rerank": false}'

# Filtresiz (karışım)
curl ... -d '{"query": "Q3 revenue growth", "use_rerank": false}'
```

Beklenen davranış: cevabı tabloda olan sorularda `chunk_types=["table"]`
sonuçları `chunk_type="table"` + `page_number` + `bbox` döner; metin filtresi
aynı soruda ya boş ya düşük benzerlik döner — bu fark multi-modal indexlemenin
değerini gösterir.

## 3) Nasıl Çalıştırılır

```bash
cd backend
# Sanal ortamda (venv) — .env GROQ_API_KEY dolu olmalı (RAGAS LLM çağırır)
.venv\Scripts\python -m scripts.run_evaluation --document-id <UUID> [--num-questions 5]
```

Akış: dokümandan `num_questions` sentetik soru üretilir → her soru için
retrieval + cevap üretilir → RAGAS puanlanır → metrikler yazdırılır.

> Test seti üretimi LLM çağrısı gerektirir; test ortamında (`GROQ_API_KEY` boş)
> endpoint testleri LLM mock'uyla koşar (bkz. `tests/test_evaluation.py`).

## 4) Test Seti Nasıl Üretilir

Multi-modal kapsama için soruları modaliteye göre çeşitlendirin:

- **Tablo:** "Q3 2026 revenue nedir?", "Net income kaç arttı?"
- **Grafik:** "2025 EBITDA grafiği ne gösteriyor?", "Hangi çeyrekte büyüme zirve yaptı?"
- **Metin:** "Yönetim kurulu raporunda risk faktörleri neler?"
- **Karma:** "Revenue büyümesinin ana nedeni ne, tablodaki rakamlarla doğrula."

Otomatik üretim: `POST /api/ai/evaluate/generate-set`
```json
{"document_id": "<UUID>", "num_questions": 8}
```

## 5) Eşik Altı Sonuçlarda Kontrol Listesi

1. `faithfulness` düşük → `MIN_SIMILARITY` (0.55) eşiğini ve rerank top_k değerini gözden geçir
2. `context_precision` düşük → embedding modelini (bge-small → daha büyük) veya chunk boyutunu değiştir
3. Tablo soruları boş dönüyor → `parse-pdf` çıktısında `tables_found`'a bak; pdfplumber tabloyu kaçırıyorsa camelot (stream/lattice) devreye alın
4. Grafik soruları placeholder dönüyor → `GROQ_API_KEY` + `VISION_MODEL`'i doğrula, sonra `POST /api/documents/{id}/reindex-images`
