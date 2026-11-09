"""PostgreSQL-only behaviour: partial unique index, RETURNING, sequences,
real concurrency and the migration's PostgreSQL storage options.

Skipped unless CUTLY_TEST_POSTGRES_URL points at an empty, disposable database
(``postgresql+asyncpg://…``). The ``public`` schema is dropped and recreated.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from container import Container
from core.enums import BroadcastAudience, BroadcastMode
from db.migrations import upgrade
from tests.conftest import make_settings, media

URL = os.environ.get("CUTLY_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="CUTLY_TEST_POSTGRES_URL is not set")


async def _reset_schema(revision: str = "head") -> None:
    engine = create_async_engine(URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: upgrade(sync, revision))
    await engine.dispose()


@pytest.fixture
async def pg(tmp_path: Path):
    await _reset_schema()
    container = Container(make_settings(tmp_path, db_url=URL))
    await container.startup()
    yield container
    await container.shutdown()


async def test_storage_tuning_and_partial_indexes(pg):
    async with pg.database.engine.connect() as connection:
        options = dict((await connection.execute(text(
            "SELECT relname, reloptions FROM pg_class WHERE relname IN ('links', 'users')"
        ))).all())
        partial = dict((await connection.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE indexname IN "
            "('ix_users_admins', 'uq_broadcasts_single_running')"
        ))).all())
    assert options == {"links": ["fillfactor=90"], "users": ["fillfactor=90"]}
    assert "WHERE is_admin" in partial["ix_users_admins"]
    assert "WHERE" in partial["uq_broadcasts_single_running"]


async def test_download_cap_with_real_concurrency(pg):
    await pg.users.ensure(10)
    link = await pg.links.create(10, [media()], expires_at=None, max_downloads=5)
    results = await asyncio.gather(*(pg.links.reserve_download(link) for _ in range(40)))
    assert sorted(r for r in results if r is not None) == [1, 2, 3, 4, 5]


async def test_single_running_broadcast_is_enforced(pg):
    await pg.users.ensure(1)
    jobs = [await pg.broadcasts.create(admin_id=1, mode=BroadcastMode.COPY, audience=BroadcastAudience.ALL,
                                       channel_ref=None, source_chat_id=1, source_message_id=1) for _ in range(5)]
    claims = await asyncio.gather(*(pg.broadcasts.claim(job) for job in jobs))
    assert claims.count(True) == 1 and claims.count(None) == 4


async def test_stats_and_backup_round_trip(pg, tmp_path):
    await pg.users.ensure(10)
    link = await pg.links.create(10, [media(), media()], expires_at=None, max_downloads=None)
    await pg.links.record_view(link, 10)
    stats = await pg.stats.dashboard()
    assert (stats.total_users, stats.total_links, stats.views_today) == (1, 1, 1)

    backup = await pg.backups.export_data()
    staged = pg.restores.stage(backup)
    await pg.restores.apply(staged)
    restored = await pg.links.create(10, [media()], expires_at=None, max_downloads=None)
    assert restored.id > link.id  # sequences were moved past the restored ids
