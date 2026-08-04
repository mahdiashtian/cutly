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
    await _migrate_existing_schema()


async def _migrate_existing_schema() -> None:
    """Add columns introduced after the initial schema to existing deployments.

    ``generate_schemas`` creates missing tables but deliberately does not alter
    existing ones.  These additive migrations keep both SQLite and PostgreSQL
    installations compatible without requiring a manual database reset.
    """
    connection = Tortoise.get_connection("default")
    dialect = connection.capabilities.dialect
    timestamp_type = "TIMESTAMPTZ" if dialect == "postgres" else "TIMESTAMP"

    if dialect == "sqlite":
        _, user_columns = await connection.execute_query('PRAGMA table_info("user")')
        _, file_columns = await connection.execute_query('PRAGMA table_info("file")')
        known_user_columns = {column["name"] for column in user_columns}
        known_file_columns = {column["name"] for column in file_columns}
        if "last_activity_at" not in known_user_columns:
            await connection.execute_query(
                f'ALTER TABLE "user" ADD COLUMN "last_activity_at" {timestamp_type}'
            )
        if "expires_at" not in known_file_columns:
            await connection.execute_query(
                f'ALTER TABLE "file" ADD COLUMN "expires_at" {timestamp_type}'
            )
        if "max_downloads" not in known_file_columns:
            await connection.execute_query('ALTER TABLE "file" ADD COLUMN "max_downloads" INT')
    else:
        await connection.execute_query(
            f'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS "last_activity_at" {timestamp_type}'
        )
        await connection.execute_query(
            f'ALTER TABLE "file" ADD COLUMN IF NOT EXISTS "expires_at" {timestamp_type}'
        )
        await connection.execute_query(
            'ALTER TABLE "file" ADD COLUMN IF NOT EXISTS "max_downloads" INT'
        )


async def close_db() -> None:
    """Close all database connections gracefully."""

    await Tortoise.close_connections()
