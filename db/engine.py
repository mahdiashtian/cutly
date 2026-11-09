"""Async SQLAlchemy engine and session factory.

PostgreSQL is the production backend. SQLite is supported for development and
tests; it gets the pragmas it needs to behave (foreign keys, WAL, busy timeout).
"""
from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db import models  # noqa: F401  (registers the tables on Base.metadata)
from db.base import Base


class Database:
    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: float = 30,
        pool_recycle: int = 1800,
        command_timeout: int = 60,
        echo: bool = False,
    ) -> None:
        self.is_sqlite = url.startswith("sqlite")
        if self.is_sqlite:
            options: dict = {"echo": echo}
            if ":memory:" in url:
                # One shared connection, or every session would see its own empty DB.
                options.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
            self.engine: AsyncEngine = create_async_engine(url, **options)
            event.listen(self.engine.sync_engine, "connect", _sqlite_pragmas)
        else:
            self.engine = create_async_engine(
                url,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_recycle=pool_recycle,
                pool_pre_ping=True,
                connect_args={"command_timeout": command_timeout},
                echo=echo,
            )
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

    async def create_all(self) -> None:
        """Tests only. Real databases are built by Alembic migrations."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - a health probe reports, never raises
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()


def _sqlite_pragmas(connection, _record) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
