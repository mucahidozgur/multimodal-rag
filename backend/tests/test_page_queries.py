"""Faz 8 sayfa hedefli sorgu + rerank anahtarı testleri."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import deterministic_user_id
from app.models.document import Chunk, Document
from app.services.prompts import build_context_block
from app.services.rag import RAGService

ALICE_ID = UUID(deterministic_user_id("alice"))

PAGE5_CONTENT = "SAYFA5 GIZLI ICERIK: BLAST protokolü adımları."
PAGE6_CONTENT = "SAYFA6 ICERIK: kurulum gereksinimleri."


def test_build_context_block_includes_page() -> None:
    """Bağlam bloğu chunk'ların sayfa numaralarını taşır."""
    chunks = [
        {
            "document_title": "rehber",
            "chunk_index": 0,
            "content": "icerik",
            "page_number": 5,
        },
        {
            "document_title": "rehber",
            "chunk_index": 1,
            "content": "eski",
            "page_number": None,
        },
    ]
    block = build_context_block(chunks)
    assert "(sayfa 5, parça 0)" in block
    assert "(parça 1)" in block  # sayfası olmayan eski chunk


async def _seed_doc_with_pages(db_session: AsyncSession, owner_id: UUID) -> UUID:
    """1 doküman: sayfa 5'te 2 chunk, sayfa 6'da 1 chunk."""
    doc = Document(title="rehber", content="", owner_id=owner_id)
    db_session.add(doc)
    await db_session.flush()
    db_session.add_all(
        [
            Chunk(
                document_id=doc.id,
                content=PAGE5_CONTENT,
                embedding=[0.0] * 384,
                chunk_index=0,
                chunk_type="text",
                page_number=5,
            ),
            Chunk(
                document_id=doc.id,
                content=PAGE5_CONTENT + " devam",
                embedding=[0.0] * 384,
                chunk_index=1,
                chunk_type="text",
                page_number=5,
            ),
            Chunk(
                document_id=doc.id,
                content=PAGE6_CONTENT,
                embedding=[0.0] * 384,
                chunk_index=2,
                chunk_type="text",
                page_number=6,
            ),
        ]
    )
    await db_session.commit()
    return doc.id


async def test_get_chunks_by_page(db_session: AsyncSession) -> None:
    """Yalnızca istenen sayfanın chunk'ları, chunk_index sırasıyla döner."""
    doc_id = await _seed_doc_with_pages(db_session, ALICE_ID)
    rag = RAGService(db_session, ALICE_ID)

    results = await rag.get_chunks_by_page([doc_id], 5, limit=10)
    assert len(results) == 2
    assert all(r["page_number"] == 5 for r in results)
    assert [r["chunk_index"] for r in results] == [0, 1]
    assert all(r["similarity"] == 1.0 for r in results)

    # Başka doküman filtresi → boş
    other = await rag.get_chunks_by_page([uuid4()], 5, limit=10)
    assert other == []


async def test_rerank_disabled_falls_back_to_hybrid(monkeypatch: pytest.MonkeyPatch) -> None:
    """RERANK_ENABLED=false iken rerank atlanır, hybrid sonuç aynen döner."""
    monkeypatch.setattr(get_settings(), "RERANK_ENABLED", False)

    marker = [{"chunk_id": "x", "similarity": 0.9, "content": "c"}]

    class _StubRag(RAGService):
        def __init__(self) -> None:
            pass

        async def search_hybrid(self, query, limit=5, alpha=0.5, chunk_types=None):
            assert query == "q"
            return marker

    result = await _StubRag().search_hybrid_rerank("q", limit=3)
    assert result == marker


def test_page_query_regex() -> None:
    """Sayfa hedefli soru deseni Türkçe/İngilizce varyantları yakalar."""
    from app.services.chat import extract_page_number

    assert extract_page_number("5. sayfada ne var") == 5
    assert extract_page_number("sayfa 12 özeti") == 12
    assert extract_page_number("what is on page 3") == 3
    assert extract_page_number("Python nedir?") is None


class _EchoLLM:
    """Son HumanMessage'ı yakalar ve içeriğini tek token olarak döner."""

    captured: list[str]

    def __init__(self) -> None:
        self.captured = []

    async def astream(self, messages, config=None):
        content = str(messages[-1].content)
        self.captured.append(content)

        class _Chunk:
            pass

        chunk = _Chunk()
        chunk.content = content
        yield chunk


def _collect_events(app_client: TestClient, body: dict, headers: dict[str, str]) -> list:
    """SSE stream'ini event listesine çevirir (test_chat ile aynı biçim)."""
    events: list[tuple[str, dict]] = []
    with app_client.stream("POST", "/api/ai/chat", json=body, headers=headers) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if not line:
                continue
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                import json

                events.append((name, json.loads(line[len("data: ") :])))
    return events


async def test_chat_specific_page_query(
    app_client: TestClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'5. sayfada ne var' sorusu doğrudan sayfa 5 chunk'larıyla cevaplanır."""
    # Dokümanı alice'e ait yap (auth ile görünür olsun).
    doc = Document(title="rehber", content="", owner_id=ALICE_ID)
    db_session.add(doc)
    await db_session.flush()
    db_session.add_all(
        [
            Chunk(
                document_id=doc.id,
                content=PAGE5_CONTENT,
                embedding=[0.0] * 384,
                chunk_index=0,
                chunk_type="text",
                page_number=5,
            ),
            Chunk(
                document_id=doc.id,
                content=PAGE6_CONTENT,
                embedding=[0.0] * 384,
                chunk_index=1,
                chunk_type="text",
                page_number=6,
            ),
        ]
    )
    await db_session.commit()

    echo = _EchoLLM()
    monkeypatch.setattr("app.services.chat.get_llm", lambda: echo)

    events = _collect_events(
        app_client, {"query": "5. sayfada ne var", "verify": False}, auth_headers
    )
    tokens = "".join(data["text"] for name, data in events if name == "token")
    assert PAGE5_CONTENT in tokens
    assert PAGE6_CONTENT not in tokens  # yalnızca sayfa 5 bağlamda
    assert echo.captured and "sayfa 5" in echo.captured[0]


async def test_chat_specific_page_query_not_found(
    app_client: TestClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Sayfada kayıtlı metin yoksa net 'metin bulunamadı' mesajı döner."""
    doc = Document(title="rehber", content="", owner_id=ALICE_ID)
    db_session.add(doc)
    await db_session.commit()

    events = _collect_events(
        app_client, {"query": "99. sayfada ne var", "verify": False}, auth_headers
    )
    tokens = "".join(data["text"] for name, data in events if name == "token")
    assert "99. sayfada metin bulunamadı" in tokens
    done = next(data for name, data in events if name == "done")
    assert done["finish_reason"] == "page_not_found"
