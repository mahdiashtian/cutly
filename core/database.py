"""Async SQLAlchemy lifecycle and Alembic schema upgrades."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from alembic import command
from alembic.config import Config
from decouple import config
from sqlalchemy import URL, event, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from core.maintenance import get_gate


def database_url() -> URL:
    """Accept legacy Tortoise DSNs and SQLAlchemy async DSNs."""
    override = config("DB_URL", default="")
    if override:
        if override.startswith("sqlite://") and not override.startswith("sqlite:///"):
            override = "sqlite+aiosqlite:///" + override[len("sqlite://") :]
        url = make_url(override)
        if url.get_backend_name() in ("postgres", "postgresql"):
            return url.set(drivername="postgresql+asyncpg")
        if url.get_backend_name() == "sqlite":
            return url.set(drivername="sqlite+aiosqlite")
        raise ValueError("DB_URL must point to SQLite or PostgreSQL")
    name = config("DB_NAME", default="")
    user = config("DB_USER", default="")
    if name and user:
        return URL.create(
            "postgresql+asyncpg",
            username=user,
            password=config("DB_PASSWORD", default=""),
            host=config("DB_HOST", default="localhost"),
            port=config("DB_PORT", default=5432, cast=int),
            database=name,
        )
    return make_url("sqlite+aiosqlite:///db.sqlite3")


def create_engine(url: str | URL) -> AsyncEngine:
    options = {"pool_pre_ping": True}
    if make_url(url).get_backend_name() in ("postgres", "postgresql"):
        options.update(
            pool_size=config("DB_POOL_SIZE", default=10, cast=int),
            max_overflow=config("DB_MAX_OVERFLOW", default=20, cast=int),
            pool_timeout=config("DB_POOL_TIMEOUT", default=30, cast=float),
            pool_recycle=config("DB_POOL_RECYCLE", default=1800, cast=int),
            pool_use_lifo=True,
        )
    engine = create_async_engine(url, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(connection, record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            if config("DB_SQLITE_WAL", default=True, cast=bool):
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessions
    if _engine is None:
        _engine = create_engine(database_url())
        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


@asynccontextmanager
async def session_scope():
    """One session per operation; commit writes or roll them back."""
    get_engine()
    assert _sessions is not None
    async with get_gate().operation():
        async with _sessions() as session:
            async with session.begin():
                yield session


def alembic_config() -> Config:
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return cfg


async def init_db() -> None:
    """Upgrade on the app's async connection, including in-memory SQLite."""

    def upgrade(connection):
        cfg = alembic_config()
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")

    try:
        async with get_engine().begin() as connection:
            await connection.run_sync(upgrade)
    except BaseException:
        await close_db()
        raise


async def close_db() -> None:
    global _engine, _sessions
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessions = None
