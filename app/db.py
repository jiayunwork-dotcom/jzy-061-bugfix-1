"""异步数据库引擎与会话（PostgreSQL 16 / asyncpg；测试可换 aiosqlite）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings

_settings = get_settings()
engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)


async def init_db() -> None:
    """建表（首启幂等）。生产建议换成 Alembic 迁移，这里保持开箱即用。"""
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个独立 session，提交/回滚互不串号。"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
