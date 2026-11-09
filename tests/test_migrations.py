"""The migrations must produce exactly the schema the ORM models describe."""
from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from db.base import Base
from db.migrations import upgrade


def test_migrations_match_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.sqlite3'}")
    with engine.begin() as connection:
        upgrade(connection)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_removes_everything(tmp_path):
    from alembic import command

    from db.migrations import alembic_config

    engine = create_engine(f"sqlite:///{tmp_path / 'down.sqlite3'}")
    with engine.begin() as connection:
        upgrade(connection)
        command.downgrade(alembic_config(connection), "base")
        tables = set(connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars())
    engine.dispose()
    assert tables == {"alembic_version"}
