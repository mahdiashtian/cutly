import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from core.database import session_scope
from core.models import File, FileAccessLog, User
from services import (
    change_admin_from_db,
    create_channel_from_db,
    create_user_from_db,
    delete_channel_from_db,
    delete_file_from_db,
    file_access_error,
    get_bot_settings,
    read_channels_from_db,
    read_file_from_db,
    read_files_from_db,
    read_user_from_db,
    read_users,
    record_file_access,
    set_global_caption,
    set_show_file_captions,
    touch_user_activity,
    userid_list,
)
from services.file import increment_file_downloads, read_album_files, save_file_fields
from services.file_repository import FileRepository
from services.user_repository import UserRepository


async def test_get_or_create_and_admin_cache(isolated_db):
    await isolated_db.set_user_list([])
    first = await create_user_from_db({"userid": 42, "phone_number": "123"})
    second = await create_user_from_db({"userid": 42, "phone_number": "changed"})
    assert first.id == second.id and second.phone_number == "123"
    assert await userid_list() == [42]
    assert await read_users(is_admin=True) == []
    assert await change_admin_from_db(42, is_staff=True)
    assert [u.userid for u in await read_users(is_admin=True)] == [42]
    assert (await read_user_from_db(42)).is_staff
    assert await change_admin_from_db(42, is_staff=False)
    assert not (await read_user_from_db(42)).is_staff
    assert not await change_admin_from_db(99999, is_staff=True)


async def test_cached_user_roundtrip_and_legacy_hydration(owner, isolated_db):
    cached = await read_user_from_db(owner.userid)
    assert cached.id == owner.id
    assert cached.created_at == owner.created_at
    await isolated_db.set_user_detail(
        owner.userid, {"userid": owner.userid, "is_staff": False, "is_superuser": False}
    )
    assert (await read_user_from_db(owner.userid)).id == owner.id
    await touch_user_activity(owner.userid)
    assert (await read_user_from_db(owner.userid)).last_activity_at.tzinfo is not None


async def test_channels_invalidate_after_success(isolated_db):
    await isolated_db.set_channel_list({"old": {}})
    channel = await create_channel_from_db(
        {"channel_id": "@test", "channel_link": "https://t.me/test"}
    )
    assert channel.is_active
    assert await isolated_db.get_channel_list() is None
    assert [c.id for c in await read_channels_from_db()] == [channel.id]
    assert await delete_channel_from_db(channel.channel_link)
    assert not await delete_channel_from_db("@missing")


async def test_file_binary_bigint_owner_and_constraints(make_file, owner):
    file = await make_file()
    loaded = await read_file_from_db(file.code)
    assert loaded.owner.userid == owner.userid
    assert loaded.owner_id == owner.userid != owner.id
    assert loaded.file_reference == b"\x00\xffref"
    assert loaded.access_hash == -6_000_000_000_001
    assert loaded.file_id == 8_000_000_000_001
    assert loaded.created_at.tzinfo is not None
    assert await read_file_from_db(file.code, userid=123) is None
    with pytest.raises(IntegrityError):
        await make_file()
    with pytest.raises(IntegrityError):
        await make_file("orphan", owner_id=12345)
    assert len(await read_files_from_db()) == 1


async def test_album_order_deletion_and_owner_scope(make_file, owner):
    await make_file("album", album_id="group", album_order=0)
    await make_file("album_part1", album_id="group", album_order=1)
    await make_file("single")
    assert [f.code for f in await read_album_files("group")] == ["album", "album_part1"]
    assert not await delete_file_from_db(123, "album")
    assert await delete_file_from_db(owner.userid, "album")
    assert [f.code for f in await read_files_from_db()] == ["single"]


async def test_cascade_delete_and_access_logs_survive(make_file, owner):
    file = await make_file()
    await record_file_access(55, file)
    await UserRepository().delete(owner.id)
    assert await read_files_from_db() == []
    async with session_scope() as session:
        assert len((await session.scalars(select(FileAccessLog))).all()) == 1


async def test_atomic_counts_and_stale_caption_do_not_reset_counter(make_file):
    file = await make_file()
    repo = FileRepository()
    await asyncio.gather(*(repo.increment_download_count(file.code) for _ in range(30)))
    file.caption = "caption"
    await save_file_fields(file, "caption")
    loaded = await read_file_from_db(file.code)
    assert loaded.count == 30 and loaded.caption == "caption"
    await increment_file_downloads([loaded])
    assert loaded.count == 31
    assert not await repo.increment_download_count("missing")


async def test_concurrent_user_and_settings_creation():
    users = await asyncio.gather(
        *(create_user_from_db({"userid": 42}) for _ in range(12))
    )
    assert len({u.id for u in users}) == 1
    settings = await asyncio.gather(*(get_bot_settings() for _ in range(12)))
    assert {s.id for s in settings} == {1}


async def test_settings_singleton_and_unicode():
    settings = await get_bot_settings()
    assert (
        settings.id == 1
        and settings.show_file_captions
        and settings.global_caption is None
    )
    await set_global_caption("کپشن عمومی")
    await set_show_file_captions(False)
    settings = await get_bot_settings()
    assert settings.global_caption == "کپشن عمومی" and not settings.show_file_captions
    await set_global_caption(None)
    assert (await get_bot_settings()).global_caption is None


@pytest.mark.parametrize(
    "expired,count,maximum,expected",
    [
        (False, 0, None, None),
        (True, 0, None, "⏰"),
        (False, 2, 2, "🚫"),
        (False, 1, 2, None),
        (True, 2, 2, "⏰"),
    ],
)
async def test_file_access_boundaries(make_file, expired, count, maximum, expected):
    file = await make_file(
        count=count,
        max_downloads=maximum,
        expires_at=datetime.now(timezone.utc) + timedelta(days=-1 if expired else 1),
    )
    result = file_access_error(file)
    assert result.startswith(expected) if expected else result is None


async def test_repositories_filter_paginate_and_update(make_file, owner):
    await make_file("photo")
    await make_file(
        "video",
        type="video",
        password="x",
        created_at=datetime.now(timezone.utc) + timedelta(seconds=1),
    )
    repo = FileRepository()
    assert [
        f.code for f in await repo.get_filtered(file_type="video", has_password=True)
    ] == ["video"]
    assert [f.code for f in await repo.get_filtered(has_password=False)] == ["photo"]
    assert len(await repo.get_user_files(owner.userid, limit=1, offset=1)) == 1
    assert await repo.count(owner_id=owner.userid) == 2
    assert await repo.exists(code="photo")
    file = await repo.get_by_code("photo")
    assert (await repo.update(file.id, {"caption": "new"})).caption == "new"
    assert await repo.update(999, {}) is None
    assert await repo.delete_by_code("photo", owner.userid)
