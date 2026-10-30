"""Cloudflare embeddings sağlayıcı testleri (HTTP mock'lu; gerçek API çağrısı yok)."""

import pytest

from app.core.config import get_settings
from app.core.llm import CloudflareEmbeddings, LocalEmbeddings, get_embeddings


class _FakeResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"result": {"data": [[0.1, 0.2], [0.3, 0.4]]}}


class _FakeClient:
    """httpx.Client yerine geçer; istek URL'ini ve gövdeyi yakalar."""

    def __init__(self) -> None:
        self.last_url: str | None = None
        self.last_json: dict | None = None

    def post(self, url: str, json: dict | None = None) -> _FakeResponse:
        self.last_url = url
        self.last_json = json
        return _FakeResponse()


def test_cloudflare_embed_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed_documents Workers AI API'sine batch gönderir, vektörleri döner."""
    fake = _FakeClient()
    monkeypatch.setattr("app.core.llm.httpx.Client", lambda **kwargs: fake)
    monkeypatch.setattr(get_settings(), "CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setattr(get_settings(), "CLOUDFLARE_API_TOKEN", "tok")

    result = CloudflareEmbeddings().embed_documents(["a", "b"])
    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert fake.last_url == "/accounts/acct-123/ai/run/@cf/baai/bge-small-en-v1.5"
    assert fake.last_json == {"text": ["a", "b"]}


def test_cloudflare_embed_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed_query tek metni gönderir ve tek vektör döner."""
    fake = _FakeClient()
    monkeypatch.setattr("app.core.llm.httpx.Client", lambda **kwargs: fake)
    monkeypatch.setattr(get_settings(), "CLOUDFLARE_ACCOUNT_ID", "acct-123")

    result = CloudflareEmbeddings().embed_query("sorgu")
    assert result == [0.1, 0.2]
    assert fake.last_json == {"text": ["sorgu"]}


def test_get_embeddings_provider_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBEDDING_PROVIDER=cloudflare → CloudflareEmbeddings; local → LocalEmbeddings."""
    monkeypatch.setattr(get_settings(), "EMBEDDING_PROVIDER", "cloudflare")
    get_embeddings.cache_clear()
    try:
        assert isinstance(get_embeddings(), CloudflareEmbeddings)
    finally:
        get_embeddings.cache_clear()

    monkeypatch.setattr(get_settings(), "EMBEDDING_PROVIDER", "local")
    get_embeddings.cache_clear()
    try:
        assert isinstance(get_embeddings(), LocalEmbeddings)
    finally:
        get_embeddings.cache_clear()
