"""Deterministic races and scaling checks for cache/transaction boundaries."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.cache import CACHE_KEY_USERS
from core.database import session_scope
from core.models import File
from services import user as user_service
from services.file import read_album_files, read_file_from_db
from services.file_repository import FileRepository
from services.user import (
    create_user_from_db,
    read_user_from_db,
    change_admin_from_db,
    userid_list,
)
from services.user_repository import UserRepository


async def test_user_list_fill_keeps_registration_that_commits_during_query(
    isolated_db, monkeypatch
):
    queried, resume = asyncio.Event(), asyncio.Event()
    original = user_service._repo.get_userids_list

    async def snapshot():
        ids = await original()
        queried.set()
        await resume.wait()
        return ids

    monkeypatch.setattr(user_service._repo, "get_userids_list", snapshot)
    fill = asyncio.create_task(userid_list())
    await asyncio.wait_for(queried.wait(), 5)
    try:
        await create_user_from_db({"userid": 42})
    finally:
        resume.set()
    await fill
    assert await isolated_db.get_user_list() == [42]


async def test_role_edit_does_not_evict_unrelated_user(owner, monkeypatch):
    await read_user_from_db(owner.userid)
    await create_user_from_db({"userid": 42})
    await change_admin_from_db(42, is_staff=True)
    monkeypatch.setattr(
        user_service._repo,
        "get_by_userid",
        AsyncMock(side_effect=AssertionError("unrelated profile lost")),
    )
    assert (await read_user_from_db(owner.userid)).userid == owner.userid


async def test_repository_role_mutation_and_delete_invalidate_cached_profile(owner):
    await read_user_from_db(owner.userid)
    repo = UserRepository()
    await repo.update(owner.id, {"is_staff": True})
    assert (await read_user_from_db(owner.userid)).is_staff
    await repo.delete(owner.id)
    assert await read_user_from_db(owner.userid) is None


async def test_moving_file_invalidates_old_and_new_album(make_file):
    file = await make_file(album_id="old")
    await read_album_files("old")
    await read_album_files("new")
    await FileRepository().update(file.id, {"album_id": "new"})
    assert await read_album_files("old") == []
    assert [row.code for row in await read_album_files("new")] == [file.code]


async def test_expired_version_cannot_accept_an_old_cache_fill(isolated_db):
    scope = "file:code"
    _, version = await isolated_db.get_snapshot(scope, "metadata")
    await isolated_db.invalidate_scope(scope)
    await isolated_db.redis.delete(f"cutly:version:{scope}")
    await isolated_db.set_snapshot(scope, "metadata", {"password": None}, version)
    assert (await isolated_db.get_snapshot(scope, "metadata"))[0] is None


async def test_deleted_original_album_member_does_not_leak_download_slots(
    make_file, telegram
):
    from core.maintenance import get_gate
    from utils.helpers import send_file
    from utils.keyboard import START_KEYBOARD

    original = await make_file("original", album_id="album", max_downloads=1)
    remaining = await make_file("remaining", album_id="album", max_downloads=1)
    await FileRepository().delete(original.id)
    result = await send_file(
        telegram,
        42,
        original,
        bot_username="bot",
        keyboard=START_KEYBOARD,
        storage_channel_id=-100555,
    )
    assert result == []
    assert get_gate().downloads == {}
    assert (await read_file_from_db(remaining.code)).count == 0


async def test_channel_title_lookup_failure_does_not_remove_join_requirement(
    app, telegram
):
    from services.channel import create_channel_from_db

    await create_channel_from_db(
        {"channel_id": "@locked", "channel_link": "https://t.me/locked"}
    )
    telegram.get_entity.side_effect = OSError("Telegram temporarily unavailable")
    channels = await app.build_channel_join_list(telegram)
    assert channels == {"@locked": {"title": "@locked", "link": "https://t.me/locked"}}


async def test_album_finalize_rolls_back_every_row_on_middle_failure(
    app, event_factory, owner, make_file, monkeypatch
):
    from core.upload_session import get_upload_manager
    from telethon import events

    await make_file("collision_part1")
    session = get_upload_manager().start_session(owner.userid)
    for index in range(3):
        session.add_file(
            message_id=55 + index,
            media_type="photo",
            size=100,
            file_id=8000000000001 + index,
            access_hash=1,
            file_reference=b"reference",
        )
    monkeypatch.setattr(
        app,
        "generate_random_text",
        lambda length: "collision" if length == 15 else "group",
    )
    with pytest.raises(events.StopPropagation):
        await app.finalize_upload(
            event_factory(user_id=owner.userid), expires_at=None, max_downloads=None
        )
    async with session_scope() as db:
        codes = set(await db.scalars(select(File.code)))
    assert codes == {"collision_part1"}
