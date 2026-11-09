"""Alembic helpers used at runtime.

Migrations are a deploy step (``alembic upgrade head``), never something every
process does on boot: the bot and several workers starting together would race
each other. Processes only *verify* the schema and refuse to start on a mismatch.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

ROOT = Path(__file__).resolve().parent.parent


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    if connection is not None:
        # migrations/env.py runs on this connection instead of opening its own.
        config.attributes["connection"] = connection
    return config


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def upgrade(connection: Connection, revision: str = "head") -> None:
    command.upgrade(alembic_config(connection), revision)


async def assert_schema_is_current(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        current = await connection.run_sync(
            lambda sync: MigrationContext.configure(sync).get_current_revision()
        )
    expected = head_revision()
    if current != expected:
        raise RuntimeError(
            f"database schema is at {current!r}, code expects {expected!r}; "
            "run `alembic upgrade head` first"
        )
