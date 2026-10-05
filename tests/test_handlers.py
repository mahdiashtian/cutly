import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from telethon import events, types
from core.state import State
from core.upload_session import get_upload_manager
from services import read_file_from_db, read_files_from_db, read_user_from_db
from services.file import read_album_files
from services.user_repository import UserRepository


async def stopped(handler, event):
    try:
        await handler(event)
    except events.StopPropagation:
        pass


async def test_start_creates_user_and_menu(app, event_factory, telegram):
    event = event_factory("/start")
    await stopped(app.handle_start, event)
    user = await read_user_from_db(event.sender_id)
    assert user and user.last_activity_at
    assert app.CONVERSATION_STATE[event.sender_id] is None
    assert telegram.send_message.call_args.kwargs["buttons"] == app.START_KEYBOARD


async def test_membership_keeps_deep_link(app, event_factory, telegram):
    from telethon.errors import UserNotParticipantError

    app.CHANNEL_JOIN_LIST = {"-100555": {"title": "Test", "link": "https://t.me/test"}}
    telegram.get_permissions.side_effect = UserNotParticipantError(request=None)
    event = event_factory("/start get_abc123")
    assert not await app.enforce_channel_membership(event)
    buttons = telegram.send_message.call_args.kwargs["buttons"]
    assert buttons[-1][0].type.url.endswith("?start=get_abc123")
    telegram.get_permissions.assert_awaited_once_with(-100555, event.sender_id)


async def test_password_download_owner_bypass_and_cleanup(
    app, make_file, event_factory, telegram, owner
):
    file = await make_file(password="secret")
    outsider = event_factory(
        "/start get_abc123",
        user_id=42,
        pattern_match=re.match(r"^/start get_(?P<code>.+)$", "/start get_abc123"),
    )
    await stopped(app.handle_get_file, outsider)
    assert app.CONVERSATION_STATE[42] == State.USER_SEND_PASSWORD_FOR_GET_FILE
    assert not telegram.send_file.called
    await app.handle_passworded_file(event_factory("wrong", user_id=42))
    assert not telegram.send_file.called
    await stopped(app.handle_passworded_file, event_factory("secret", user_id=42))
    assert (await read_file_from_db(file.code)).count == 1
    assert app.CONVERSATION_STATE[42] is None
    assert app.LIST_VIDEO == [{"chat_id": 100, "message_id": 10}]
    own_event = event_factory("/start get_abc123", pattern_match=outsider.pattern_match)
    await app.handle_get_file(own_event)
    assert (await read_file_from_db(file.code)).count == 2
    await app.cleanup_messages(telegram)
    assert app.LIST_VIDEO == [] and telegram.delete_messages.await_count == 2


async def test_expired_and_missing_file_do_not_send(
    app, make_file, event_factory, telegram
):
    await make_file(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    event = event_factory(
        "/start get_abc123",
        pattern_match=re.match(r".*get_(?P<code>.+)$", "/start get_abc123"),
    )
    await stopped(app.handle_get_file, event)
    assert not telegram.send_file.called
    event.pattern_match = re.match(r".*get_(?P<code>.+)$", "/start get_missing")
    await stopped(app.handle_get_file, event)
    assert not telegram.send_file.called


@pytest.mark.parametrize(
    "field,start_state,get_handler,set_handler,unset_handler",
    [
        (
            "password",
            State.USER_SEND_TEXT_FOR_SET_PASSWORD,
            "handle_get_password_object",
            "handle_set_password",
            "handle_unset_password",
        ),
        (
            "caption",
            State.USER_SEND_TEXT_FOR_SET_CAPTION,
            "handle_get_caption_object",
            "handle_set_caption",
            "handle_unset_caption",
        ),
    ],
)
async def test_caption_password_edit_and_ownership(
    app,
    make_file,
    event_factory,
    field,
    start_state,
    get_handler,
    set_handler,
    unset_handler,
):
    file = await make_file()
    await stopped(getattr(app, get_handler), event_factory(file.code, user_id=42))
    assert 42 not in app.CONVERSATION_OBJECT
    await stopped(getattr(app, get_handler), event_factory(file.code))
    assert app.CONVERSATION_STATE[file.owner_id] == start_state
    await stopped(getattr(app, set_handler), event_factory("new value"))
    assert getattr(await read_file_from_db(file.code), field) == "new value"
    await stopped(getattr(app, unset_handler), event_factory(file.code))
    assert getattr(await read_file_from_db(file.code), field) is None


async def test_upload_finalize_preserves_media_and_album_parts(app, event_factory):
    event = event_factory()
    await stopped(app.handle_upload_prompt, event)
    session = get_upload_manager().get_session(event.sender_id)
    session.add_file(10, "photo", 100, 1001, -1002, b"ref1")
    session.add_file(11, "video", 200, 2001, -2002, b"ref2")
    await stopped(app.handle_finish_upload, event)
    assert app.CONVERSATION_STATE[event.sender_id] == State.USER_SET_FILE_LIMITS
    await stopped(app.handle_file_limits, event_factory("7 3"))
    files = await read_files_from_db(userid=event.sender_id)
    assert len(files) == 2
    assert files[1].code == files[0].code + "_part1"
    assert files[0].album_id == files[1].album_id
    assert [f.file_reference for f in files] == [b"ref1", b"ref2"]
    assert [f.max_downloads for f in files] == [3, 3]
    assert all(
        f.expires_at > datetime.now(timezone.utc) + timedelta(days=6) for f in files
    )
    assert get_upload_manager().get_session(event.sender_id) is None


@pytest.mark.parametrize("text", ["0 3", "7 0", "- -", "wrong", "x 1", "-1 3"])
async def test_invalid_upload_limits_keep_session(app, event_factory, text):
    event = event_factory(text)
    session = get_upload_manager().start_session(event.sender_id)
    session.add_file(10, "photo", 100, 1001, -1002, b"ref")
    await app.handle_file_limits(event)
    assert get_upload_manager().get_session(event.sender_id) is session
    assert await read_files_from_db() == []


async def test_upload_cancel_keeps_storage_files_as_before(
    app, event_factory, telegram
):
    event = event_factory()
    session = get_upload_manager().start_session(event.sender_id)
    session.add_file(10, "photo", 100, 1001, -1002, b"ref")
    await stopped(app.handle_cancel_upload, event)
    assert get_upload_manager().get_session(event.sender_id) is None
    assert not telegram.delete_messages.called and await read_files_from_db() == []


async def test_history_groups_albums_and_delete_is_scoped(
    app, make_file, event_factory, telegram
):
    await make_file("album", album_id="group", album_order=0)
    await make_file("album_part1", album_id="group", album_order=1)
    await stopped(app.handle_file_history, event_factory())
    text = telegram.send_message.call_args.args[1]
    assert "_part1" not in text and "album" in text
    await stopped(app.handle_delete_file, event_factory("album", user_id=42))
    assert len(await read_album_files("group")) == 2
    await stopped(app.handle_delete_file, event_factory("album"))
    assert await read_album_files("group") == []


async def test_broadcast_segments_and_channel_members(app, owner, telegram):
    now = datetime.now(timezone.utc)
    await UserRepository().create(
        {
            "userid": 42,
            "created_at": now - timedelta(days=10),
            "last_activity_at": now - timedelta(days=40),
        }
    )
    await UserRepository().create(
        {"userid": 43, "created_at": now - timedelta(days=8), "last_activity_at": now}
    )
    assert [
        u.userid for u in await app.get_broadcast_audience(telegram, "🆕 کاربران جدید")
    ] == [owner.userid]
    assert [
        u.userid for u in await app.get_broadcast_audience(telegram, "🟢 کاربران فعال")
    ] == [43]
    assert [
        u.userid
        for u in await app.get_broadcast_audience(telegram, "⚪ کاربران غیرفعال")
    ] == [owner.userid, 42]

    async def membership(channel_id, user_id):
        if user_id != 43:
            raise ValueError("not joined")

    telegram.get_permissions.side_effect = membership
    assert [
        u.userid
        for u in await app.get_broadcast_audience(
            telegram, "📢 اعضای کانال", "@channel"
        )
    ] == [43]


@pytest.mark.parametrize(
    "attribute,media_type",
    [
        (types.DocumentAttributeVideo(duration=1, w=1, h=1), "video"),
        (types.DocumentAttributeAudio(duration=1, voice=True), "voice"),
        (types.DocumentAttributeAudio(duration=1), "audio"),
        (types.DocumentAttributeAnimated(), "animation"),
        (types.DocumentAttributeFilename("file.txt"), "document"),
    ],
)
def test_telethon_media_detection(app, attribute, media_type):
    document = types.Document(
        id=10,
        access_hash=-20,
        file_reference=b"ref",
        date=datetime.now(timezone.utc),
        mime_type="application/octet-stream",
        size=2048,
        dc_id=2,
        attributes=[attribute],
    )
    message = SimpleNamespace(
        media=types.MessageMediaDocument(document=document), document=document
    )
    assert app.detect_media_payload(message) == (media_type, 2048, 10, -20, b"ref")


async def test_filters_private_state_and_admin(app, event_factory, owner):
    from utils.filters import admin_filter, compose_filters, conversation, private_only

    event = event_factory()
    pred = compose_filters(
        private_only(), conversation(app.CONVERSATION_STATE, None), admin_filter(999)
    )
    assert not await pred(event)
    from services import change_admin_from_db

    await change_admin_from_db(owner.userid, is_staff=True)
    assert await pred(event)
    event.is_private = False
    assert not await pred(event)


async def test_single_upload_forwards_media_and_keeps_identifiers(
    app, event_factory, telegram
):
    photo = types.Photo(
        id=10,
        access_hash=-20,
        file_reference=b"photo",
        date=datetime.now(timezone.utc),
        sizes=[types.PhotoSize(type="x", w=100, h=100, size=1024)],
        dc_id=2,
    )
    event = event_factory()
    event.message = SimpleNamespace(
        text="",
        sticker=None,
        grouped_id=None,
        media=types.MessageMediaPhoto(photo=photo),
        photo=photo,
    )
    session = get_upload_manager().start_session(event.sender_id)
    await app.handle_upload_file(event)
    assert len(session.files) == 1
    file = session.files[0]
    assert (file.message_id, file.file_id, file.access_hash, file.file_reference) == (
        55,
        10,
        -20,
        b"photo",
    )
    telegram.forward_messages.assert_awaited_once_with(-100555, event.message)


async def test_album_upload_is_collected_once(app, event_factory, telegram):
    photo = types.Photo(
        id=10,
        access_hash=-20,
        file_reference=b"photo",
        date=datetime.now(timezone.utc),
        sizes=[types.PhotoSize(type="x", w=100, h=100, size=1024)],
        dc_id=2,
    )
    event = event_factory()
    event.messages = [
        SimpleNamespace(media=types.MessageMediaPhoto(photo=photo), photo=photo)
        for _ in range(2)
    ]
    telegram.forward_messages.return_value = [
        SimpleNamespace(id=55),
        SimpleNamespace(id=56),
    ]
    session = get_upload_manager().start_session(event.sender_id)
    await app.handle_upload_album(event)
    assert [file.message_id for file in session.files] == [55, 56]


async def test_broadcast_schedule_uses_tehran_timezone(app, event_factory, monkeypatch):
    from unittest.mock import Mock
    from zoneinfo import ZoneInfo

    when = (datetime.now(ZoneInfo("Asia/Tehran")) + timedelta(days=1)).replace(
        second=0, microsecond=0
    )
    event = event_factory(when.strftime("%Y-%m-%d %H:%M"))
    draft = app.BroadcastDraft(
        admin_id=event.sender_id, message=event.message, delivery_type="copy"
    )
    app.BROADCAST_DRAFTS[event.sender_id] = draft
    scheduler = Mock()
    monkeypatch.setattr(app, "SCHEDULER", scheduler)
    await app.handle_broadcast_schedule(event)
    assert scheduler.add_job.call_args.kwargs["run_date"] == when.astimezone(
        timezone.utc
    )
    assert event.sender_id not in app.BROADCAST_DRAFTS
