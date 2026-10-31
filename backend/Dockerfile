FROM python:3.11-slim

WORKDIR /app

# torch için GNU OpenMP runtime gerekli (python:3.11-slim'de yok).
# camelot-py[cv]'nin opencv'si libGL + glib ister; ghostscript + poppler-utils
# camelot/pdfplumber'ın bazı PDF işleme yolları için gerekli (Faz 1+).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgomp1 libgl1 libglib2.0-0 ghostscript poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Bağımlılık katmanını cache'leyebilmek için önce sadece pyproject.toml kopyalanır.
# pip install . paket keşfi için bir paket dizini ister; bu yüzden geçici bir app
# iskeleti oluşturulur. Gerçek kaynak sonraki katmanda COPY ile gelir (çalışma
# anında compose'taki ./backend:/app bind mount'u zaten kaynağı sağlar).
# --timeout/--retries: yavaş ağlarda büyük wheel'lerin (torch vb.) indirilmesini
# dayanıklı kılar (ReadTimeoutError nedeniyle build başarısızlığı yaşanıyordu).
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && pip install --no-cache-dir --timeout 120 --retries 5 .

COPY . .

EXPOSE 8000

# Render (ve genel PaaS) $PORT env'iyle gelir ve uygulamanın O portu dinlemesini
# bekler; yerelde (docker compose) PORT set değildir → 8000 kullanılır.
# Prod'da --reload yok (dosya izleme süreci Render'da gereksizdir).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
