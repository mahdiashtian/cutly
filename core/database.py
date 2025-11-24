"""Tortoise ORM database configuration and lifecycle helpers."""

from __future__ import annotations

from typing import Final

from tortoise import Tortoise

from app.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_URL_OVERRIDE,
    DB_USER,
)

DEFAULT_SQLITE_URL: Final[str] = "sqlite://db.sqlite3"

if DB_URL_OVERRIDE:
    TORTOISE_DB_URL: str = DB_URL_OVERRIDE
elif DB_NAME and DB_USER:
    TORTOISE_DB_URL = f"postgres://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
else:
    TORTOISE_DB_URL = DEFAULT_SQLITE_URL


async def init_db() -> None:
    """Initialize and migrate the Tortoise ORM schema.

    Examples:
        >>> await init_db()

    Raises:
        ConfigurationError: Raised when the provided DSN cannot be parsed.
    """

    await Tortoise.init(db_url=TORTOISE_DB_URL, modules={"models": ["core.models"]})
    await Tortoise.generate_schemas()


async def close_db() -> None:
    """Close all database connections gracefully."""

    await Tortoise.close_connections()
