"""Uygulama ayarları: .env dosyasından okunur."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo kökü: backend/ (config.py → app/core/config.py → parents[2]).
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Fin-RAG yapılandırma değerleri."""

    DATABASE_URL: str = "postgresql+asyncpg://multi:multi@localhost:5435/multi"
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_MODEL: str = "qwen/qwen3.8-27b"
    # Faz 3: Groq Vision (grafik/figure okuma). llama-3.2-90b-vision-preview
    # Groq'ta kaldırıldı; güncel vision modeli llama-4-scout (17b-16e).
    VISION_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    JWT_SECRET: str = "changeme"
    JWT_ALG: str = "HS256"
    JWT_EXPIRE_MIN: int = 60
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3002",
        "http://localhost:3003",
    ]
    # Langfuse observability — boş anahtarlarda trace'ler devre dışı kalır (uygulama çökmez).
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    TEST_DATABASE_URL: str | None = None  # host'tan test DB'si (localhost)
    TEST_DATABASE_URL_DOCKER: str | None = None  # container içinden test DB'si (postgres)
    # Faz 1: PDF'ten çıkarılan görsellerin kaydedileceği kök dizin (backend/storage).
    STORAGE_DIR: str = str(BASE_DIR / "storage")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Ayarları cache'leyerek döndürür (process başına tek instance)."""
    return Settings()
