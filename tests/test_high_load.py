"""Bounded tasks, cold-cache contention, live counters and cancellation."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import event, select, text

from core.cache import CACHE_KEY_USERS, CACHE_KEY_USER_MEMBERS, USER_TTL, VERSION_TTL
from core.concurrency import KeyedLocks, bounded_map
from core.database import get_engine, session_scope
from core.models import File
from services import file as files, user as users, settings
from services.analytics import get_dashboard_statistics
from services.file import (
    read_file_from_db,
    read_album_files,
    reserve_file_downloads,
    finish_file_downloads,
)
from services.user import (
    create_user_from_db,
    read_user_from_db,
    change_admin_from_db,
    userid_list,
)


async def test_cold_profile_requests_share_one_sql_read(
    owner, isolated_db, monkeypatch
):
    await isolated_db.invalidate_user_detail(owner.userid)
    original = users._repo.get_by_userid
    query = AsyncMock(side_effect=original)
    monkeypatch.setattr(users._repo, "get_by_userid", query)
    result = await asyncio.wait_for(
        asyncio.gather(*(read_user_from_db(owner.userid) for _ in range(300))), 20
    )
    assert len(result) == 300 and {user.id for user in result} == {owner.id}
    assert query.await_count == 1
    assert isolated_db._fills.entries == {}


async def test_cold_file_and_album_requests_share_metadata_queries(
    make_file, monkeypatch, isolated_db
):
    file = await make_file(album_id="group")
    metadata = AsyncMock(side_effect=files._repo.get_by_code)
    monkeypatch.setattr(files._repo, "get_by_code", metadata)
    result = await asyncio.wait_for(
        asyncio.gather(*(read_file_from_db(file.code) for _ in range(100))), 20
    )
    assert len(result) == 100 and metadata.await_count == 1
    albums = AsyncMock(side_effect=files._repo.list)
    monkeypatch.setattr(files._repo, "list", albums)
    result = await asyncio.wait_for(
        asyncio.gather(*(read_album_files("group") for _ in range(100))), 20
    )
    assert len(result) == 100 and albums.await_count == 1
    assert isolated_db._fills.entries == {}


async def test_cold_settings_singleton_uses_one_loader(monkeypatch):
    load = AsyncMock(side_effect=settings._load_settings)
    monkeypatch.setattr(settings, "_load_settings", load)
    result = await asyncio.wait_for(
        asyncio.gather(*(settings.get_bot_settings() for _ in range(300))), 20
    )
    assert {row.id for row in result} == {1} and load.await_count == 1


async def test_stale_profile_and_admin_list_fills_cannot_restore_revoked_role(
    owner, isolated_db
):
    from services.user import _cache_data

    await change_admin_from_db(owner.userid, is_staff=True)
    old = await read_user_from_db(owner.userid)
    profile_version = await isolated_db.user_version(owner.userid)
    admin_version = await isolated_db.version("admins")
    await change_admin_from_db(owner.userid, is_staff=False)
    assert not await isolated_db.set_user_detail(
        owner.userid, _cache_data(old), version=profile_version
    )
    assert not await isolated_db.set_admin_list([owner.userid], version=admin_version)
    assert not (await read_user_from_db(owner.userid)).is_staff


async def test_evicted_user_index_is_rebuilt_even_after_a_partial_add(
    owner, isolated_db
):
    assert await userid_list() == [owner.userid]
    await isolated_db.redis.delete(CACHE_KEY_USER_MEMBERS)
    await create_user_from_db({"userid": 42})
    assert await isolated_db.get_user_list() is None
    assert set(await userid_list()) == {42, owner.userid}


async def test_user_index_additions_do_not_transfer_whole_100k_list(isolated_db):
    await isolated_db.set_user_list(list(range(1, 100001)))
    get = Mock(wraps=isolated_db.redis.get)
    add = Mock(wraps=isolated_db.redis.zadd)
    isolated_db.redis.get, isolated_db.redis.zadd = get, add
    assert await isolated_db.add_user_to_list(200001)
    assert get.call_args.args == (CACHE_KEY_USERS,)
    assert add.call_count == 1 and len(add.call_args.args[1]) == 1
    assert len(await isolated_db.get_user_list()) == 100001


async def test_profile_activity_keeps_ttl_and_object_versions_expire(
    owner, make_file, isolated_db
):
    await read_user_from_db(owner.userid)
    ttl = await isolated_db.redis.ttl(f"cutly:user:{owner.userid}")
    assert 0 < ttl <= USER_TTL
    await isolated_db.update_user_activity(owner.userid, "2026-10-08T12:00:00+00:00")
    assert 0 < await isolated_db.redis.ttl(f"cutly:user:{owner.userid}") <= ttl
    file = await make_file()
    await files.save_file_fields(file, "caption")
    assert (
        0
        < await isolated_db.redis.ttl(f"cutly:version:file:{file.code}")
        <= VERSION_TTL
    )


async def test_independent_downloads_do_not_wait_for_an_unrelated_database_read(
    make_file, monkeypatch
):
    slow = await make_file("slow")
    fast = await make_file("fast")
    entered, resume = asyncio.Event(), asyncio.Event()
    original = files.session_scope

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def blocked():
        if asyncio.current_task().get_name() == "slow-reservation":
            entered.set()
            await resume.wait()
        async with original() as session:
            yield session

    monkeypatch.setattr(files, "session_scope", blocked)
    task = asyncio.create_task(reserve_file_downloads([slow]), name="slow-reservation")
    await asyncio.wait_for(entered.wait(), 5)
    try:
        assert await asyncio.wait_for(reserve_file_downloads([fast]), 2)
        await finish_file_downloads([fast], success=False)
    finally:
        resume.set()
        await task
        await finish_file_downloads([slow], success=False)


async def test_keyed_lock_cancellation_releases_every_waiter_entry():
    locks = KeyedLocks()
    entered = asyncio.Event()

    async def wait():
        async with locks.hold(["a", "b"]):
            entered.set()

    async with locks.hold(["a"]):
        task = asyncio.create_task(wait())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not entered.is_set() and locks.entries == {}


async def test_bounded_map_10000_items_uses_five_workers_and_keeps_order():
    workers = set()

    async def process(value):
        workers.add(asyncio.current_task())
        await asyncio.sleep(0)
        return value * 2

    result = await bounded_map(process, list(range(10000)), concurrency=5)
    assert result == [index * 2 for index in range(10000)] and len(workers) == 5


async def test_bounded_map_failure_leaves_no_pending_worker():
    workers = set()

    async def process(value):
        workers.add(asyncio.current_task())
        if value == 0:
            raise ValueError("failed")
        await asyncio.Event().wait()

    with pytest.raises(ValueError, match="failed"):
        await bounded_map(process, list(range(100)), concurrency=5)
    assert all(task.done() for task in workers)


async def test_sqlite_writer_commits_while_snapshot_reader_remains_open(make_file):
    file = await make_file()
    async with get_engine().connect() as reader:
        await reader.execute(text("BEGIN"))
        await reader.execute(select(File))
        # Before WAL, the reader keeps this writer's COMMIT blocked.
        await asyncio.wait_for(files._repo.increment_download_count(file.code), 3)
        assert (
            await reader.scalar(select(File.count).where(File.code == file.code)) == 0
        )
        await reader.rollback()
    assert (await read_file_from_db(file.code)).count == 1


async def test_dashboard_is_one_sql_statement_and_immediately_fresh(make_file):
    file = await make_file(count=7)
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert (await get_dashboard_statistics())["downloads"] == 7
        assert len(statements) == 1
        await files._repo.increment_download_count(file.code)
        assert (await get_dashboard_statistics())["downloads"] == 8
    finally:
        event.remove(engine, "before_cursor_execute", record)


async def test_restore_parser_cancellation_finishes_thread_before_deleting_spool(
    tmp_path, monkeypatch
):
    from services import restore

    entered, resume = threading.Event(), threading.Event()
    path = tmp_path / "input.sql"
    path.write_text("COPY public.user (id,userid) FROM stdin;\n", encoding="utf-8")

    def parse(source, spool, source_format, stop):
        with spool.open("w", encoding="utf-8") as stream:
            entered.set()
            assert resume.wait(5)
            assert stop.is_set()
            stream.write("worker finished")
        return None

    monkeypatch.setattr(restore, "_parse", parse)
    task = asyncio.create_task(restore.prepare_restore(path))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        resume.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list((tmp_path / "backup").glob("restore-*"))


async def test_restore_cancellation_after_commit_disables_cache_and_clears_runtime(
    make_file, monkeypatch
):
    from services.backup import create_data_backup
    from services.restore import prepare_restore, apply_restore
    from core.cache import get_cache

    file = await make_file()
    prepared = await prepare_restore(await create_data_backup())
    await files._repo.increment_download_count(file.code)
    runtime_cleanup = AsyncMock()
    monkeypatch.setattr(
        get_cache(),
        "reset_after_restore",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await apply_restore(prepared, on_restored=runtime_cleanup)
        assert not get_cache().enabled
        runtime_cleanup.assert_awaited_once()
        assert (await read_file_from_db(file.code)).count == 0
    finally:
        prepared.close()


def test_import_with_both_real_session_types_without_a_loop(tmp_path):
    from telethon.sessions import StringSession
    from telethon.crypto import AuthKey

    session = StringSession()
    session.set_dc(2, "149.154.167.51", 443)
    session.auth_key = AuthKey(bytes(256))
    root = Path(__file__).resolve().parent.parent
    for encoded in ("", session.save()):
        env = {
            **os.environ,
            "SESSION_STRING": encoded,
            "SESSION_NAME": str(tmp_path / "telegram"),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import main; assert len(main.CLIENT.list_event_handlers()) == 66",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr


def test_idle_conversations_do_not_accumulate_entries(app):
    from core.state import State

    for user_id in range(100000):
        app.set_state(user_id, State.USER_UPLOAD_FILE)
        app.CONVERSATION_OBJECT[user_id] = object()
        app.reset_context(user_id)
    assert app.CONVERSATION_STATE == {} and app.CONVERSATION_OBJECT == {}


async def test_double_cancellation_never_leaks_a_pending_download(make_file, telegram):
    from core.maintenance import get_gate
    from utils.helpers import send_file
    from utils.keyboard import START_KEYBOARD

    file = await make_file(max_downloads=1)
    sending = asyncio.Event()

    async def send(*args, **kwargs):
        sending.set()
        await asyncio.Event().wait()

    telegram.send_file.side_effect = send
    task = asyncio.create_task(
        send_file(
            telegram,
            42,
            file,
            bot_username="bot",
            keyboard=START_KEYBOARD,
            storage_channel_id=-100555,
        )
    )
    await asyncio.wait_for(sending.wait(), 5)
    async with get_gate().download_lock.hold([file.code]):
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert get_gate().downloads == {} and get_gate().download_lock.entries == {}
    assert (await read_file_from_db(file.code)).count == 0


async def test_restore_waits_for_sql_and_cache_mutation_to_finish(
    isolated_db, monkeypatch
):
    from core.maintenance import get_gate

    entered, resume, restoring = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = isolated_db.add_user_to_list

    async def add(*args, **kwargs):
        entered.set()
        await resume.wait()
        return await original(*args, **kwargs)

    async def restore():
        async with get_gate().restoration():
            restoring.set()

    monkeypatch.setattr(isolated_db, "add_user_to_list", add)
    creator = asyncio.create_task(create_user_from_db({"userid": 42}))
    await asyncio.wait_for(entered.wait(), 5)
    writer = asyncio.create_task(restore())
    await asyncio.sleep(0)
    assert not restoring.is_set()
    resume.set()
    await asyncio.wait_for(asyncio.gather(creator, writer), 5)
    assert restoring.is_set()


async def test_explicit_missing_version_never_accepts_a_profile_fill(
    owner, isolated_db
):
    from services.user import _cache_data

    assert not await isolated_db.set_user_detail(
        owner.userid, _cache_data(owner), version=None
    )
    assert not await isolated_db.set_user_list([owner.userid], version=None)
    assert not await isolated_db.set_admin_list([owner.userid], version=None)
    assert not await isolated_db.set_channel_list({"old": {}}, version=None)


async def test_redis_recovery_clears_stale_namespace_before_enabling_reads(
    isolated_db, monkeypatch
):
    import fakeredis
    from core import cache as module

    stale_server = fakeredis.FakeServer()
    stale = fakeredis.FakeAsyncRedis(server=stale_server, decode_responses=True)
    await stale.set("cutly:user:42", "stale role")
    await stale.set("other:keep", "value")
    isolated_db._requested_enabled = True
    isolated_db.require_reset()
    monkeypatch.setattr(module.aioredis.Redis, "from_pool", lambda pool: stale)
    assert await isolated_db.recover()
    assert isolated_db.enabled
    assert await stale.get("cutly:user:42") is None
    assert await stale.get("other:keep") == "value"
    assert not module._reset_marker().exists()


async def test_channel_refresh_does_not_publish_stale_payload_with_new_version(
    app, telegram, monkeypatch
):
    from services.channel import create_channel_from_db, delete_channel_from_db

    await create_channel_from_db(
        {"channel_id": "@old", "channel_link": "https://t.me/old"}
    )
    original = app.build_channel_join_list
    calls = 0

    async def read(client):
        nonlocal calls
        calls += 1
        payload = await original(client)
        if calls == 1:
            await delete_channel_from_db("@old")
        return payload

    monkeypatch.setattr(app, "build_channel_join_list", read)
    await app.refresh_channel_join_cache(telegram)
    assert app.CHANNEL_JOIN_LIST == {} and calls == 2


async def test_large_album_queries_stay_below_bind_parameter_limits(owner):
    from sqlalchemy import insert
    from core.models import File
    from services.file import increment_file_downloads

    size = 1500
    async with session_scope() as session:
        await session.execute(
            insert(File),
            [
                dict(
                    type="photo",
                    code=f"part-{index}",
                    owner_id=owner.userid,
                    size=100,
                    file_id=8000000000001 + index,
                    access_hash=1,
                    file_reference=b"ref",
                    message_id=index + 1,
                    album_id="large",
                    album_order=index,
                )
                for index in range(size)
            ],
        )
    records = await read_album_files("large")
    await read_album_files("large")
    engine = get_engine().sync_engine

    def check(connection, cursor, statement, parameters, context, executemany):
        if " IN (" in statement:
            assert len(parameters) <= 999

    event.listen(engine, "before_cursor_execute", check)
    try:
        counts = await reserve_file_downloads(records)
        assert len(counts) == size
        await finish_file_downloads(records, success=True)
        assert set(await files._repo.counts_by_code([row.code for row in records])) == {
            row.code for row in records
        }
        assert all(row.count == 1 for row in records)
    finally:
        event.remove(engine, "before_cursor_execute", check)


async def test_cancelling_counter_lock_wait_releases_download_reservation(make_file):
    from core.maintenance import get_gate

    file = await make_file(max_downloads=1)
    gate = get_gate()
    await reserve_file_downloads([file])
    async with gate.download_lock.hold([file.code]):
        task = asyncio.create_task(finish_file_downloads([file], success=True))
        await asyncio.sleep(0)
        assert gate.download_lock.entries[file.code][1] == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.downloads == {}
    assert gate.download_lock.entries == {}
    assert (await read_file_from_db(file.code)).count == 0


async def test_bulk_user_id_change_invalidates_both_profiles_and_index(
    owner, isolated_db
):
    from core.models import User
    from services.user_repository import UserRepository

    await read_user_from_db(owner.userid)
    assert await userid_list() == [owner.userid]
    assert await UserRepository().update_where({"userid": 42}, User.id == owner.id) == 1
    assert await read_user_from_db(owner.userid) is None
    assert (await read_user_from_db(42)).id == owner.id
    assert await userid_list() == [42]


async def test_cancelling_committed_role_invalidation_bypasses_old_cache(
    owner, isolated_db, monkeypatch
):
    from services.user_repository import UserRepository

    await change_admin_from_db(owner.userid, is_staff=True)
    assert (await read_user_from_db(owner.userid)).is_staff
    entered = asyncio.Event()
    original = isolated_db.redis.set

    async def blocked(key, *args, **kwargs):
        if key == f"cutly:version:user:{owner.userid}":
            entered.set()
            await asyncio.Future()
        return await original(key, *args, **kwargs)

    monkeypatch.setattr(isolated_db.redis, "set", blocked)
    task = asyncio.create_task(change_admin_from_db(owner.userid, is_staff=False))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (await UserRepository().get_by_userid(owner.userid)).is_staff
    assert not isolated_db.enabled
    assert await isolated_db.get_user_detail(owner.userid) is None
    assert (Path(os.environ["BACKUP_DIR"]) / "cache-reset-required").exists()
