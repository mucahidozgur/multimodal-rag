# Fin-RAG Demo Senaryosu (5-7 dk)

Demo öncesi hazırlık:

```bash
docker compose up -d          # postgres + api + web
# .env içinde GROQ_API_KEY dolu olmalı (VLM + LLM için)
```

Örnek PDF: finansal rapor benzeri, **tablo + grafik görseli** içeren 2-3
sayfalık bir PDF. (Test için `backend/storage/samples/demo.pdf` veya kendi
10-Q örneğiniz kullanılabilir.)

---

### 1) Login (30 sn)
- http://localhost:3003 → alice / x ile giriş (mock auth; her kullanıcı geçerli)
- **Söylenecek:** "Her kullanıcının kendi dokümanları ve arama alanı var."

### 2) PDF Yükle → Parse + Index (90 sn)
- Dokümanlar → **Yeni Doküman → PDF Yükle** sekmesi
- PDF'i sürükle: "Yükleniyor... → Parse ediliyor... → Indexleniyor..." progress'i
- **Söylenecek:** "PDF üç modaliteye ayrılıyor: metin, tablo, görsel. Her biri
  ayrı vektör uzayına gömülüyor; tablolar markdown'a çevriliyor, grafikler
  VLM ile okunuyor."

### 3) Chat: "Q3 revenue nedir?" (60 sn)
- AI Asistan → soruyu sor
- Cevap tablo chunk'ından gelir; "📎 Kaynaklar" altında tablo kaynağı
  **sayfa numarasıyla** listelenir; verification bloğu "✅ destekleniyor" der.
- **Söylenecek:** "Bu cevap metinden değil tablodan geldi — text-only RAG bunu
  bulamazdı."

### 4) Chat: "2025 EBITDA grafiği ne gösteriyor?" (60 sn)
- Cevap image chunk'ından (VLM açıklaması) gelir: eksenler, trend, değerler.
- **Söylenecek:** "Groq Vision grafiği okudu ve açıklamayı indexledi —
  grafik artık sorgulanabilir."

### 5) Chat: Alakasız Soru (30 sn)
- "Gelecek yılın piyango sonuçları nedir?" → sabit "bilgi yok" cevabı, LLM
  çağrılmaz (güven eşiği).
- **Söylenecek:** "Yetersiz bağlamda LLM'e hiç gidilmez — uydurma riski sıfır."

### 6) Citation → PDF Viewer + bbox Highlight (60 sn)
- Adım 3'teki cevapta kaynak chip'ine tıkla → PDFViewer açılır, ilgili sayfa
  gelir, tablonun üzerinde **sarı kutu + turuncu çerçeve**.
- **Söylenecek:** "Citation yalnızca sayfayı değil, sayfadaki tam konumu
  gösteriyor — 500 sayfalık raporda avukat saniyeler içinde kaynağı bulur."

### 7) Admin Dashboard: KPI Kartları (30 sn)
- Analytics sayfası: toplam sorgu, ortalama faithfulness, yetersiz bağlam
  oranı, gecikme, feedback oranı.
- **Söylenecek:** "Her sorgu metrikleniyor; kalite düşüşü anında görünür."

### 8) Langfuse Trace: Sorgu İzleme (30 sn)
- `.env`'de `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` doluysa: Langfuse'ta
  `search_hybrid`, `rerank`, `verify_citations` span'leri ve feedback'ler.
- **Söylenecek:** "Opsiyonel observability — anahtarsız tamamen no-op."

---

**Toplam:** ~6 dakika. Vurgu cümlesi: *"Metin + tablo + grafik tek arama
yüzeyinde, her cevap sayfa ve piksel hassasiyetinde kaynağa bağlı."*
