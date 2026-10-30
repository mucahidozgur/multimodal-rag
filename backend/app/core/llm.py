"""LLM ve embedding soyutlama katmanı."""

from functools import lru_cache

import httpx
from langchain_openai import ChatOpenAI

from app.core.config import get_settings

settings = get_settings()


@lru_cache
def get_llm() -> ChatOpenAI:
    """Groq üzerindeki chat modelini cache'leyerek döndürür."""
    return ChatOpenAI(
        base_url=settings.GROQ_BASE_URL,
        api_key=settings.GROQ_API_KEY,
        model=settings.LLM_MODEL,
        temperature=0,
        streaming=True,
    )


# Faz 3: Groq Vision (multimodal) modeli. langchain-groq paketi ağır bir
# bağımlılık zinciri getirmediği için modül import'unda içe aktarılır; ancak
# paket eksikse uygulama ayağa kalkmalı diye import fonksiyon içinde (lazy)
# yapılır — ilk vision çağrısına kadar hata görülmez.
_vision_llm = None


def get_vision_llm():
    """Groq Vision modelini tek instance olarak (lazy) döndürür."""
    global _vision_llm
    if _vision_llm is None:
        from langchain_groq import ChatGroq  # lazy: paket yoksa yalnızca burada patlar

        _vision_llm = ChatGroq(
            model=settings.VISION_MODEL,
            api_key=settings.GROQ_API_KEY,
            max_tokens=500,
            temperature=0,
            request_timeout=60,
        )
    return _vision_llm


class CloudflareEmbeddings:
    """Cloudflare Workers AI üzerinden embedding üretir (ücretsiz katman, 384 dim).

    Faz 7: Render free tier'da RAM tasarrufu için lokal modele alternatif.
    Aynı model (bge-small-en-v1.5) → aynı 384 boyutlu vektör uzayı.
    """

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url="https://api.cloudflare.com/client/v4",
            headers={"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}"},
            timeout=30.0,
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Workers AI REST API'sine batch gönderir, vektörleri döndürür."""
        url = (
            f"/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}"
            f"/ai/run/{settings.CLOUDFLARE_EMBEDDING_MODEL}"
        )
        response = self._client.post(url, json={"text": texts})
        response.raise_for_status()
        return response.json()["result"]["data"]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Doküman listesini embedding vektörlerine çevirir."""
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        """Tek bir sorgu metnini embedding vektörüne çevirir."""
        return self._embed([text])[0]


class LocalEmbeddings:
    """Yerel sentence-transformers modeliyle embedding üretir."""

    @property
    @lru_cache  # noqa: B019 (spec: property üzerinde lru_cache; tek instance üzerinden çağrılır)
    def _model(self):
        """Modeli bir kez yükler ve cache'ler.

        torch import'u yalnızca burada yapılır (lazy) — cloudflare sağlayıcı
        seçiliyse (Render) ağır bağımlılık RAM'e hiç yüklenmez.
        """
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(settings.EMBEDDING_MODEL)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Doküman listesini normalize embedding vektörlerine çevirir."""
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        """Tek bir sorgu metnini embedding vektörüne çevirir."""
        return self.embed_documents([text])[0]


@lru_cache
def get_embeddings():
    """EMBEDDING_PROVIDER'a göre embedding sağlayıcısını döndürür.

    "cloudflare" → Workers AI (Render/free tier); varsayılan "local" →
    sentence-transformers (lokal geliştirme + testler).
    """
    if settings.EMBEDDING_PROVIDER == "cloudflare":
        return CloudflareEmbeddings()
    return LocalEmbeddings()


# Cross-encoder singleton'ı. Model ~2 GB indirir ve RAM tüketir; bu yüzden
# modül import'unda DEĞİL, ilk rerank çağrısında (lazy) yüklenir. Docker
# imajına model dahil değildir — çalışma anında hf_cache volume'üne iner.
_reranker = None


def get_reranker():
    """Cross-encoder reranker'ı tek instance olarak (lazy) döndürür."""
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(settings.RERANKER_MODEL)
    return _reranker
