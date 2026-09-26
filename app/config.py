"""应用配置：数据库地址、持久化开关等，全部可经环境变量覆盖。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PASCHEN_", env_file=None)

    # 生产（docker-compose）默认指向 PostgreSQL 16；
    # 本地/测试可用 sqlite+aiosqlite 跑，DATABASE_URL 由环境注入。
    database_url: str = (
        "postgresql+asyncpg://paschen:paschen@localhost:5432/paschen"
    )
    # 设为 0 可关闭落库（核算本身不受影响）。
    persist_enabled: bool = True
    service_name: str = "paschen-breakdown-service"


@lru_cache
def get_settings() -> Settings:
    return Settings()
