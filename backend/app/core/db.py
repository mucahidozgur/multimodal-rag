"""Async SQLAlchemy altyapısı."""

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Tüm ORM modellerinin ortak declarative tabanı."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: her istek için bir async session verir."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """pgvector uzantısını hazırlar; tabloları create_all ile oluşturur.

    Bulut dağıtımında (Neon/Render) alembic migration koşulmadığı için
    self-bootstrap (idempotent); yerelde mevcut tablolar için no-op'tur.
    DB erişilemezse uyarı basar ve geçer (health endpoint'i ayakta kalır).
    """
    try:
        import app.models  # noqa: F401  (tabloları Base.metadata'ya kaydeder)

        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:  # noqa: BLE001 (spec: DB erişilemezse sessizce geç)
        logger.warning(f"DB init skipped: {e}")
