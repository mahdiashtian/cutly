"""PostgreSQL-only behaviour: partial unique index, RETURNING, sequences,
real concurrency and the migration on PostgreSQL.

Skipped unless CUTLY_TEST_POSTGRES_URL points at an empty, disposable database
(``postgresql+asyncpg://…``). The ``public`` schema is dropped and recreated.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from container import Container
from core.enums import BroadcastAudience, BroadcastMode
from core.security import verify_password
from db.migrations import upgrade
from db.models import Link, LinkMedia, User
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


async def test_migration_converts_legacy_rows_on_postgres(tmp_path):
    await _reset_schema("0001_sqlalchemy")
    engine = create_async_engine(URL)
    statements = (
        """INSERT INTO "user" (id, userid, created_at, is_superuser, is_staff)
           VALUES (1, 500, now(), false, true), (2, 600, now(), false, false)""",
        """INSERT INTO file (id, type, size, code, file_id, access_hash, file_reference, message_id, count,
                             password, caption, album_id, album_order, created_at, owner_id) VALUES
           (1, 'photo', 1, 'abc', 1, 1, '\\x01', 1, 4, 'pw', 'c', 'A', 0, now(), 500),
           (2, 'video', 2, 'abc_part1', 2, 2, '\\x02', 2, 4, 'pw', 'c', 'A', 1, now(), 500),
           (3, 'document', 3, 'single', 3, 3, '\\x03', 3, 0, NULL, NULL, NULL, 0, now(), 600)""",
        """INSERT INTO file_access_log (id, viewer_id, file_code, owner_id, accessed_at)
           VALUES (1, 600, 'abc', 500, now())""",
    )
    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: upgrade(sync, "head"))
        admins = (await connection.execute(select(User.id).where(User.is_admin))).scalars().all()
        links = {row.code: row for row in await connection.execute(select(Link.__table__))}
        positions = (await connection.execute(
            select(LinkMedia.position, LinkMedia.media_type).where(LinkMedia.link_id == links["abc"].id)
            .order_by(LinkMedia.position))).all()
    await engine.dispose()
    assert admins == [500]
    assert set(links) == {"abc", "single"} and verify_password("pw", links["abc"].password_hash)
    assert positions == [(0, "photo"), (1, "video")]
