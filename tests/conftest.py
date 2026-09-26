"""测试夹具：用 SQLite 内存库替换 PostgreSQL，验证与数据库无关的行为。

物理内核测试不需要库；API 测试通过依赖覆盖把会话指向同一个内存 SQLite，
建表逻辑复用生产环境的同一套 ORM 元数据。
"""

from __future__ import annotations

import os

# 必须在导入应用模块之前设置，让 config/db 采用 sqlite。
os.environ.setdefault(
    "PASCHEN_DATABASE_URL", "sqlite+aiosqlite:///./test_paschen.db"
)
os.environ.setdefault("PASCHEN_PERSIST_ENABLED", "true")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app.db import get_session
from app.main import app
from app.models import Base


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # 内存库跨连接共享同一条连接
        future=True,
    )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 让 service 层的 get_settings 缓存保持开启，只覆盖会话依赖。
    async def override_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, maker
    app.dependency_overrides.clear()
    await engine.dispose()
