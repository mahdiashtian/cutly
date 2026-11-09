"""Alembic helpers used at runtime.

``python main.py`` upgrades the schema once, *before* it starts the Celery
processes, so no two processes ever race to migrate. A restore also uses these
helpers to rebuild a backup's schema in a staging database.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
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


def known_revisions() -> set[str]:
    return {script.revision for script in ScriptDirectory.from_config(alembic_config()).walk_revisions()}


def upgrade(connection: Connection, revision: str = "head") -> None:
    command.upgrade(alembic_config(connection), revision)


async def upgrade_to_head(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(upgrade)
