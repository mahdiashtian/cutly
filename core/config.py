"""Application settings, loaded once from the environment / ``.env``.

Every tunable lives here so the rest of the code never reads ``os.environ``.
The connection defaults match the services in ``docker-compose.yml``, so a
copied ``.env.example`` works with ``docker compose up -d`` out of the box.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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

    # ---- PostgreSQL ----
    db_url: str = "postgresql+asyncpg://cutly:cutly@127.0.0.1:25432/cutly"
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
    redis_cache_url: str = "redis://127.0.0.1:26379/0"
    redis_state_url: str = "redis://127.0.0.1:26380/0"
    redis_max_connections: int = 64
    # Empty means: use the state Redis.
    celery_broker_url: str = ""

    # ---- Cache & state lifetimes (seconds) ----
    # Entities are written through on every change; the TTL only bounds the
    # damage of a rare read/write race and keeps cold keys from living forever.
    cache_ttl_seconds: int = 86_400
    # Only a *positive* membership answer is cached (see bot.membership).
    forced_join_cache_seconds: int = 60
    # An abandoned conversation or upload session expires on its own.
    conversation_ttl_seconds: int = 86_400
    # last_active_at is written at most once per window per user, instead of on
    # every message; broadcast segments only need day-level precision.
    activity_touch_seconds: int = 300

    # ---- Abuse protection ----
    # Updates one user may send per window; extra ones are dropped (one notice).
    user_rate_limit: int = 30
    user_rate_window_seconds: int = 10
    # Wrong passwords allowed per user and link per window (brute-force guard;
    # it also caps how much scrypt CPU one user can make the bot spend).
    password_attempts: int = 5
    password_window_seconds: int = 900

    # ---- Background workers ----
    # True: ``python main.py`` also starts the Celery worker and beat processes.
    # Set False when they run as separate services (e.g. several worker hosts).
    embedded_workers: bool = True
    worker_concurrency: int = 4

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

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_state_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
