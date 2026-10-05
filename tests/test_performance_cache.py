import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services import file as file_service
from services import settings as settings_service
from services import user as user_service
from services.analytics import touch_user_activity
from services.file import (
    read_file_from_db,
    read_album_files,
    save_file_fields,
    delete_file_from_db,
)
from services.settings import get_bot_settings, set_global_caption
from services.user import read_user_from_db, change_admin_from_db
from utils.helpers import send_file
from utils.keyboard import START_KEYBOARD
from telethon.errors import FileReferenceExpiredError


async def test_file_cache_keeps_live_counts_and_owner_checks(
    make_file, isolated_db, monkeypatch
):
    file = await make_file(max_downloads=3)
    await read_file_from_db(file.code)
    monkeypatch.setattr(
        file_service._repo,
        "get_by_code",
        AsyncMock(side_effect=AssertionError("metadata should be cached")),
    )
    assert (await read_file_from_db(file.code)).count == 0
    await file_service._repo.increment_download_count(file.code)
    assert (await read_file_from_db(file.code)).count == 1
    assert await read_file_from_db(file.code, userid=42) is None


async def test_edits_and_deletes_invalidate_file_album_metadata(make_file, isolated_db):
    file = await make_file(album_id="album")
    assert (await read_album_files("album"))[0].caption is None
    await read_file_from_db(file.code)
    file.caption = "new"
    file.password = "secret"
    await save_file_fields(file, "caption", "password")
    assert (await read_file_from_db(file.code)).password == "secret"
    assert (await read_album_files("album"))[0].caption == "new"
    await delete_file_from_db(file.owner_id, file.code)
    assert await read_file_from_db(file.code) is None
    assert await read_album_files("album") == []


async def test_activity_keeps_detail_cached_with_updated_timestamp(owner, monkeypatch):
    original = await read_user_from_db(owner.userid)
    await touch_user_activity(owner.userid)
    monkeypatch.setattr(
        user_service._repo,
        "get_by_userid",
        AsyncMock(side_effect=AssertionError("no repeated user SELECT")),
    )
    updated = await read_user_from_db(owner.userid)
    assert updated.id == original.id and updated.last_activity_at is not None


async def test_late_cache_activity_update_cannot_move_timestamp_back(
    owner, isolated_db
):
    from services.user import _cache_data

    await isolated_db.update_user_activity(owner.userid, "2026-10-05T12:00:00+00:00")
    await isolated_db.update_user_activity(owner.userid, "2026-10-05T11:00:00+00:00")
    await isolated_db.set_user_detail(owner.userid, _cache_data(owner))
    assert (await isolated_db.get_user_detail(owner.userid))[
        "last_activity_at"
    ] == "2026-10-05T12:00:00+00:00"


async def test_stale_cache_fill_is_rejected(isolated_db):
    _, version = await isolated_db.get_snapshot("file", "code")
    await isolated_db.invalidate_scope("file")
    await isolated_db.set_snapshot("file", "code", {"password": None}, version)
    assert (await isolated_db.get_snapshot("file", "code"))[0] is None


async def test_channel_fill_cannot_restore_removed_configuration(isolated_db):
    version = await isolated_db.version("channels")
    await isolated_db.invalidate_channel_cache()
    assert not await isolated_db.set_channel_list(
        {"old": {"title": "old", "link": "old"}}, version=version
    )
    assert await isolated_db.get_channel_list() is None


async def test_settings_cache_updates_immediately(monkeypatch):
    await set_global_caption("first")
    assert (await get_bot_settings()).global_caption == "first"
    # Warm reads have no database session.
    original = settings_service.session_scope

    def fail():
        raise AssertionError("settings should be cached")

    monkeypatch.setattr(settings_service, "session_scope", fail)
    assert (await get_bot_settings()).global_caption == "first"
    monkeypatch.setattr(settings_service, "session_scope", original)
    await set_global_caption("second")
    assert (await get_bot_settings()).global_caption == "second"


async def test_expired_telegram_reference_refreshes_and_invalidates_cache(
    make_file, telegram
):
    file = await make_file()
    await read_file_from_db(file.code)
    telegram.send_file.side_effect = [
        FileReferenceExpiredError(request=None),
        SimpleNamespace(id=88, chat_id=42),
    ]
    telegram.get_messages = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=file.message_id,
                photo=SimpleNamespace(
                    id=file.file_id, access_hash=99, file_reference=b"fresh"
                ),
            )
        ]
    )
    await send_file(
        telegram,
        42,
        file,
        bot_username="bot",
        keyboard=START_KEYBOARD,
        storage_channel_id=-100555,
    )
    restored = await read_file_from_db(file.code)
    assert (
        restored.file_reference == b"fresh"
        and restored.access_hash == 99
        and restored.count == 1
    )
    telegram.get_messages.assert_awaited_once_with(-100555, ids=[file.message_id])


async def test_clear_all_scans_only_application_namespace(isolated_db):
    await isolated_db.redis.set("other:keep", "value")
    for index in range(1100):
        await isolated_db.redis.set(f"cutly:test:{index}", "value")
    isolated_db.redis.keys = AsyncMock(side_effect=AssertionError("KEYS blocks Redis"))
    assert await isolated_db.clear_all()
    assert await isolated_db.redis.get("other:keep") == "value"
    assert await isolated_db.redis.dbsize() == 1


async def test_concurrent_downloads_cannot_exceed_limit(make_file, telegram):
    file = await make_file(max_downloads=3)
    files = [await read_file_from_db(file.code) for _ in range(20)]
    results = await asyncio.gather(
        *(
            send_file(
                telegram,
                42,
                record,
                bot_username="bot",
                keyboard=START_KEYBOARD,
                storage_channel_id=-100555,
            )
            for record in files
        )
    )
    assert sum(bool(result) for result in results) == 3
    assert telegram.send_file.await_count == 3
    assert (await read_file_from_db(file.code)).count == 3


async def test_pending_delivery_does_not_enter_backup_or_permanent_counter(
    make_file, telegram, tmp_path, monkeypatch
):
    from services.backup import create_data_backup
    from services.restore import prepare_restore
    import sqlite3, json
    from contextlib import closing

    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    file = await make_file(max_downloads=1)
    started, release = asyncio.Event(), asyncio.Event()

    async def deliver(*args, **kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(id=88, chat_id=42)

    telegram.send_file.side_effect = deliver
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
    await started.wait()
    try:
        assert (await read_file_from_db(file.code)).count == 0
        prepared = await prepare_restore(await create_data_backup())
        try:
            with closing(sqlite3.connect(prepared.spool)) as connection:
                payload = connection.execute(
                    "SELECT payload FROM rows WHERE table_name='file'"
                ).fetchone()[0]
            assert json.loads(payload)["count"] == 0
        finally:
            prepared.close()
    finally:
        release.set()
        await task
    assert (await read_file_from_db(file.code)).count == 1
