"""Optional integration checks against disposable PostgreSQL and Redis services."""

import asyncio
import os
from pathlib import Path
import uuid

import asyncpg
import pytest
from sqlalchemy import make_url, select
from core.cache import RedisCache
from core.database import close_db, get_engine, init_db, session_scope
from core.models import User
from services import (
    create_file_from_db,
    create_user_from_db,
    delete_file_from_db,
    get_bot_settings,
    get_dashboard_statistics,
    read_file_from_db,
    record_file_access,
)
from services.file import save_file_fields
from services.file_repository import FileRepository


@pytest.mark.parametrize("legacy", [False, True])
async def test_postgres_fresh_and_legacy_databases(monkeypatch, legacy, telegram):
    dsn = os.environ.get("CUTLY_TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("Set CUTLY_TEST_POSTGRES_URL to a disposable PostgreSQL admin DSN")
    await close_db()
    url = make_url(dsn)
    admin = await asyncpg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    name = "cutly_test_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{name}"')
    test_url = url.set(database=name, drivername="postgresql+asyncpg")
    monkeypatch.setenv("DB_URL", test_url.render_as_string(hide_password=False))
    try:
        if legacy:
            connection = await asyncpg.connect(
                test_url.set(drivername="postgresql").render_as_string(
                    hide_password=False
                )
            )
            try:
                await connection.execute(
                    (
                        Path(__file__).parent / "fixtures" / "legacy_postgres.sql"
                    ).read_text(encoding="utf-8")
                )
                await connection.execute(
                    'INSERT INTO "user" (userid) VALUES (5000000002)'
                )
                await connection.execute(
                    """INSERT INTO "file"
                    (type,size,code,file_id,access_hash,file_reference,message_id,owner_id,password,caption,count)
                    VALUES ('photo',2048,'legacy',8000000000001,-6000000000001,$1,55,5000000002,'secret','کپشن',2)""",
                    b"\x00\xffref",
                )
            finally:
                await connection.close()
        await init_db()
        await init_db()
        if legacy:
            original = await read_file_from_db("legacy")
            assert original.password == "secret" and original.caption == "کپشن"
            assert original.count == 2 and original.file_reference == b"\x00\xffref"
            assert original.owner.userid == 5000000002
        owner = await create_user_from_db({"userid": 5_000_000_001})
        file = await create_file_from_db(
            dict(
                code="protected",
                owner_id=owner.userid,
                type="photo",
                size=2048,
                file_id=8_000_000_000_001,
                access_hash=-6_000_000_000_001,
                file_reference=b"\x00\xffref",
                message_id=55,
                caption="کپشن",
                password="secret",
                max_downloads=5,
            )
        )
        loaded = await read_file_from_db(file.code)
        assert (
            loaded.file_reference == b"\x00\xffref"
            and loaded.owner.userid == owner.userid
        )
        assert loaded.created_at.tzinfo is not None
        await asyncio.gather(
            *(FileRepository().increment_download_count(file.code) for _ in range(20))
        )
        from utils.helpers import send_file
        from utils.keyboard import START_KEYBOARD
        capped = await create_file_from_db(dict(
            code="capped", owner_id=owner.userid, type="photo", size=100,
            file_id=8000000000002, access_hash=-6000000000002,
            file_reference=b"ref", message_id=56, max_downloads=3,
        ))
        copies = [await read_file_from_db(capped.code) for _ in range(10)]
        deliveries = await asyncio.gather(*(send_file(telegram, 42, item,
            bot_username="test", keyboard=START_KEYBOARD, storage_channel_id=-100555) for item in copies))
        assert sum(bool(result) for result in deliveries) == 3
        assert (await read_file_from_db(capped.code)).count == 3
        await delete_file_from_db(owner.userid, capped.code)
        file.caption = "updated"
        await save_file_fields(file, "caption")
        assert (await read_file_from_db(file.code)).count == 20
        await record_file_access(42, file)
        assert (await get_dashboard_statistics())["views_today"] == 1
        assert (await get_bot_settings()).show_file_captions
        assert not await delete_file_from_db(42, file.code)
        assert await delete_file_from_db(owner.userid, file.code)
        from alembic import command
        from core.database import alembic_config

        async with get_engine().begin() as connection:

            def check(sync):
                config = alembic_config()
                config.attributes["connection"] = sync
                command.check(config)

            await connection.run_sync(check)
    finally:
        await close_db()
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()


async def test_real_redis_cache_contract(monkeypatch):
    dsn = os.environ.get("CUTLY_TEST_REDIS_URL")
    if not dsn:
        pytest.skip("Set CUTLY_TEST_REDIS_URL to a disposable Redis instance")
    import redis.asyncio as redis

    cache = RedisCache()
    cache.enabled = True
    cache.redis = redis.Redis.from_url(dsn, decode_responses=True)
    # Dedicated service only: the test creates the normal application cache keys.
    try:
        assert await cache.ping()
        await cache.set_user_list([])
        await asyncio.gather(*(cache.add_user_to_list(i) for i in range(30)))
        assert sorted(await cache.get_user_list()) == list(range(30))
        await cache.set_admin_list([42])
        assert await cache.get_admin_list() == [42]
        await cache.set_user_detail(42, {"userid": 42, "is_staff": True})
        assert (await cache.get_user_detail(42))["is_staff"]
        await cache.invalidate_user_detail(42)
        assert await cache.get_user_detail(42) is None
        await cache.set_channel_list(
            {"test": {"title": "Test", "link": "https://t.me/test"}}
        )
        assert "test" in await cache.get_channel_list()
        await cache.invalidate_channel_cache()
        assert await cache.get_channel_list() is None
    finally:
        await cache.clear_all()
        await cache.close()
