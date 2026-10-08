"""Real services, realistic dataset sizes, disposable databases only."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import time
import uuid

import asyncpg
import pytest
from sqlalchemy import make_url, event

from core.cache import RedisCache
from core.database import close_db, init_db, get_engine
from core.maintenance import get_gate
from services import create_user_from_db, create_file_from_db, read_file_from_db
from services.analytics import get_dashboard_statistics, get_user_access_page
from utils.helpers import send_file
from utils.keyboard import START_KEYBOARD


@pytest.mark.parametrize(
    "variable", ["CUTLY_TEST_POSTGRES_URL", "CUTLY_TEST_POSTGRES_SECOND_URL"]
)
async def test_large_postgres_dataset_and_1000_concurrent_downloads(
    variable, monkeypatch, telegram, app
):
    if not os.environ.get(variable):
        pytest.skip("A disposable PostgreSQL admin URL is required")
    url = make_url(os.environ[variable]).set(drivername="postgresql")
    admin = await asyncpg.connect(url.render_as_string(hide_password=False))
    name = "cutly_scale_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{name}"')
    target = url.set(database=name)
    await close_db()
    monkeypatch.setenv(
        "DB_URL",
        target.set(drivername="postgresql+asyncpg").render_as_string(
            hide_password=False
        ),
    )
    seed = None
    try:
        await init_db()
        owner = await create_user_from_db({"userid": 5000000001})
        guard = await create_file_from_db(
            dict(
                type="photo",
                code="guard",
                owner_id=owner.userid,
                size=100,
                file_id=8000000000001,
                access_hash=1,
                file_reference=b"ref",
                message_id=55,
                max_downloads=3,
            )
        )
        seed = await asyncpg.connect(target.render_as_string(hide_password=False))
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=365)
        size = 100000
        await seed.copy_records_to_table(
            "user",
            schema_name="public",
            columns=[
                "id",
                "userid",
                "created_at",
                "is_superuser",
                "is_staff",
                "last_activity_at",
            ],
            records=(
                (
                    index + 2,
                    1000000 + index,
                    now if index % 100 == 0 else old,
                    False,
                    False,
                    now if index % 100 == 0 else None,
                )
                for index in range(size)
            ),
        )
        await seed.copy_records_to_table(
            "file",
            schema_name="public",
            columns=[
                "id",
                "owner_id",
                "type",
                "code",
                "size",
                "file_id",
                "access_hash",
                "file_reference",
                "message_id",
                "count",
                "album_order",
                "created_at",
            ],
            records=(
                (
                    index + 2,
                    owner.userid,
                    "photo",
                    f"bulk-{index}",
                    1024,
                    9000000000000 + index,
                    1,
                    b"ref",
                    index + 100,
                    3,
                    0,
                    old,
                )
                for index in range(size)
            ),
        )
        await seed.copy_records_to_table(
            "file_access_log",
            schema_name="public",
            columns=["id", "viewer_id", "file_code", "owner_id", "accessed_at"],
            records=(
                (
                    index + 1,
                    1000000 + index % 1000,
                    f"bulk-{index % size}",
                    owner.userid,
                    now,
                )
                for index in range(size * 2)
            ),
        )
        await seed.execute("ANALYZE")
        statements = []

        def record(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = get_engine().sync_engine
        event.listen(engine, "before_cursor_execute", record)
        start = time.perf_counter()
        try:
            stats = await get_dashboard_statistics()
        finally:
            event.remove(engine, "before_cursor_execute", record)
        dashboard_ms = (time.perf_counter() - start) * 1000
        assert len(statements) == 1
        assert stats["total_users"] == size + 1 and stats["total_files"] == size + 1
        assert stats["new_today"] == size // 100 + 1 and stats["files_today"] == 1
        assert stats["downloads"] == size * 3 and stats["views_today"] == size * 2
        rows, total, viewer = await get_user_access_page(1000000, 0)
        assert len(rows) == 10 and total == 100 and viewer.userid == 1000000
        assert all(row["view_count"] == 2 for row in rows)
        active = await app.get_broadcast_audience(telegram, "🟢 کاربران فعال")
        assert len(active) == size // 100
        plan = await seed.fetchval(
            "EXPLAIN (ANALYZE, FORMAT JSON) SELECT id FROM file_access_log WHERE viewer_id=$1",
            1000000,
        )
        assert "Index" in plan

        async def download():
            file = await read_file_from_db(guard.code)
            return await send_file(
                telegram,
                42,
                file,
                bot_username="bot",
                keyboard=START_KEYBOARD,
                storage_channel_id=-100555,
            )

        start = time.perf_counter()
        results = await asyncio.wait_for(
            asyncio.gather(*(download() for _ in range(1000))), 120
        )
        assert sum(bool(result) for result in results) == 3
        assert telegram.send_file.await_count == 3
        assert (await read_file_from_db(guard.code)).count == 3
        assert get_gate().downloads == {} and get_gate().download_lock.entries == {}
        assert (await get_dashboard_statistics())["downloads"] == size * 3 + 3
        print(
            json.dumps(
                {
                    "postgres": await seed.fetchval("SHOW server_version"),
                    "users": size + 1,
                    "files": size + 1,
                    "access_logs": size * 2,
                    "dashboard_queries": len(statements),
                    "dashboard_ms": round(dashboard_ms, 2),
                    "concurrent_downloads": 1000,
                    "delivered": 3,
                    "download_seconds": round(time.perf_counter() - start, 2),
                }
            )
        )
    finally:
        if seed is not None:
            await seed.close()
        await close_db()
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()


async def test_real_redis_100k_index_and_1000_readers_wait_for_small_pool(monkeypatch):
    from core import cache as module

    dsn = os.environ.get("CUTLY_TEST_REDIS_URL")
    if not dsn:
        pytest.skip("A disposable Redis URL is required")
    url = make_url(dsn)
    monkeypatch.setattr(module, "REDIS_HOST", url.host)
    monkeypatch.setattr(module, "REDIS_PORT", url.port)
    monkeypatch.setattr(module, "REDIS_DB", int(url.database or 0))
    monkeypatch.setenv("REDIS_MAX_CONNECTIONS", "4")
    monkeypatch.setenv("REDIS_POOL_TIMEOUT", "30")
    cache = RedisCache()
    cache.enabled = True
    assert await cache.connect()
    try:
        assert await cache.clear_all()
        assert await cache.set_user_list(list(range(1, 100001)))
        start = time.perf_counter()
        assert all(
            await asyncio.wait_for(
                asyncio.gather(
                    *(cache.add_user_to_list(200000 + index) for index in range(1000))
                ),
                60,
            )
        )
        ids = await cache.get_user_list()
        assert len(ids) == 101000 and len(set(ids)) == 101000
        assert await cache.set_user_detail(42, {"userid": 42, "is_staff": False})
        reads = await asyncio.wait_for(
            asyncio.gather(*(cache.get_user_detail(42) for _ in range(1000))), 60
        )
        assert all(row and row["userid"] == 42 for row in reads)
        assert cache.redis.connection_pool.max_connections == 4
        print(
            json.dumps(
                {
                    "redis_users": len(ids),
                    "concurrent_adds": 1000,
                    "concurrent_profile_reads": 1000,
                    "connections": 4,
                    "seconds": round(time.perf_counter() - start, 2),
                }
            )
        )
    finally:
        await cache.clear_all()
        await cache.close()
