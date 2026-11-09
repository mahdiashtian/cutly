"""Alembic environment.

* ``alembic upgrade head`` (CLI): connects with the async URL from settings.
* Programmatic use (restore staging, tests): the caller passes a ready
  synchronous connection in ``config.attributes["connection"]``.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import get_settings
from db import models  # noqa: F401  (registers the tables)
from db.base import Base

config = context.config
if config.config_file_name and not config.attributes.get("connection"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    engine = create_async_engine(get_settings().db_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=get_settings().db_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif (provided := config.attributes.get("connection")) is not None:
    run_migrations(provided)
else:
    asyncio.run(run_async())
