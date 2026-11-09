"""Application settings, loaded once from the environment / ``.env``.

Every tunable lives here so the rest of the code never reads ``os.environ``.
Legacy variable names from the previous release (``DB_NAME``..., ``REDIS_HOST``...)
are still understood, so an existing ``.env`` keeps working after the upgrade.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    environment: Literal["production", "test"] = "production"
    log_level: str = "INFO"

    # ---- Telegram ----
    api_id: int = 0
    api_hash: str = ""
    bot_token: str = ""
    session_name: str = "cutly"
    session_string: str = ""
    # The owner: always an admin, never stored in (or removable from) the database.
    admin_master: int | None = None
    # Private channel every upload is forwarded to; it keeps a durable copy so an
    # expired Telegram file reference can be refreshed.
    storage_channel_id: int = 0

    # ---- PostgreSQL / SQLite ----
    db_url: str = ""
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_host: str = "localhost"
    db_port: int = 5432
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 30
    db_pool_recycle: int = 1800
    # asyncpg has no statement timeout by default; a stuck query would hold its
    # connection until restart.
    db_command_timeout: int = 60
    db_echo: bool = False

    # ---- Redis ----
    # The cache Redis is disposable (LRU eviction is fine); the state Redis holds
    # conversations, upload sessions and the Celery queue, so it must not evict.
    # Both default to REDIS_URL so a single instance works for small deployments.
    redis_url: str = ""
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_cache_url: str = ""
    redis_state_url: str = ""
    redis_max_connections: int = 64
    celery_broker_url: str = ""

    # ---- Cache & state lifetimes (seconds) ----
    # Entities are written through on every change; the TTL only bounds the
    # damage of a rare read/write race and keeps cold keys from living forever.
    cache_ttl_seconds: int = 86_400
    # Only a *positive* membership answer is cached (see services.membership).
    forced_join_cache_seconds: int = 60
    # An abandoned conversation or upload session expires on its own.
    conversation_ttl_seconds: int = 86_400
    # last_active_at is written at most once per window per user, instead of on
    # every message; broadcast segments only need day-level precision.
    activity_touch_seconds: int = 300

    # ---- Features ----
    delete_after_seconds: int = 30
    upload_max_files: int = 100
    broadcast_rate_per_second: float = 15
    broadcast_page_size: int = 200
    timezone: str = "Asia/Tehran"
    creator_username: str = ""

    # ---- Backups ----
    backup_dir: Path = Path("backup")
    restore_max_bytes: int = 2 * 1024**3
    pg_dump_path: str = ""
    pg_tool_timeout: int = 900

    @model_validator(mode="after")
    def _resolve_urls(self) -> Settings:
        self.db_url = _normalise_db_url(self.db_url) or self._assembled_db_url()
        if not self.redis_url:
            password = f":{quote(self.redis_password, safe='')}@" if self.redis_password else ""
            self.redis_url = f"redis://{password}{self.redis_host}:{self.redis_port}/{self.redis_db}"
        self.redis_cache_url = self.redis_cache_url or self.redis_url
        self.redis_state_url = self.redis_state_url or self.redis_url
        self.celery_broker_url = self.celery_broker_url or self.redis_state_url
        return self

    def _assembled_db_url(self) -> str:
        if self.db_name and self.db_user:
            password = quote(self.db_password, safe="")
            return (
                f"postgresql+asyncpg://{self.db_user}:{password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        return "sqlite+aiosqlite:///db.sqlite3"

    @property
    def bot_id(self) -> int:
        return int(self.bot_token.split(":", 1)[0]) if ":" in self.bot_token else 0


def _normalise_db_url(url: str) -> str:
    """Accept the legacy ``sqlite://`` / ``postgres://`` spellings."""
    if not url:
        return ""
    if url.startswith("sqlite://") and not url.startswith("sqlite:///"):
        url = "sqlite:///" + url[len("sqlite://"):]
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
