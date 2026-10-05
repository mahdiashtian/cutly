"""Isolated databases, Redis and Telegram doubles; no production credentials."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ["API_ID"] = "12345"
os.environ["API_HASH"] = "0" * 32
os.environ["BOT_TOKEN"] = "12345:test-token"
os.environ["ADMIN_MASTER"] = "999"
os.environ["SESSION_NAME"] = ":memory:"
os.environ["SESSION_STRING"] = ""
os.environ["REDIS_ENABLED"] = "false"

from telethon.sessions import StringSession
from telethon.crypto import AuthKey

_session = StringSession()
_session.set_dc(2, "149.154.167.51", 443)
_session.auth_key = AuthKey(bytes(256))
os.environ["SESSION_STRING"] = _session.save()

import fakeredis
import pytest
import pytest_asyncio
from core import cache as cache_module
from core.database import close_db, init_db
from core.cache import RedisCache
from services.user import create_user_from_db
from services.file import create_file_from_db


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path, monkeypatch):
    await close_db()
    monkeypatch.setenv(
        "DB_URL", "sqlite+aiosqlite:///" + (tmp_path / "test.sqlite3").as_posix()
    )
    cache = RedisCache()
    cache.enabled = True
    cache.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(cache_module, "_cache_instance", cache)
    await init_db()
    yield cache
    await cache.close()
    await close_db()


@pytest_asyncio.fixture
async def owner():
    return await create_user_from_db({"userid": 5_000_000_001})


@pytest_asyncio.fixture
async def make_file(owner):
    async def make(code="abc123", **values):
        return await create_file_from_db(
            {
                "code": code,
                "owner_id": owner.userid,
                "type": "photo",
                "size": 2048,
                "file_id": 8_000_000_000_001,
                "access_hash": -6_000_000_000_001,
                "file_reference": b"\x00\xffref",
                "message_id": 55,
                **values,
            }
        )

    return make


@pytest.fixture
def telegram():
    client = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(id=1)),
        send_file=AsyncMock(return_value=SimpleNamespace(id=10, chat_id=100)),
        forward_messages=AsyncMock(return_value=SimpleNamespace(id=55)),
        get_permissions=AsyncMock(return_value=SimpleNamespace(is_admin=False)),
        get_entity=AsyncMock(return_value=SimpleNamespace(title="Channel")),
        delete_messages=AsyncMock(),
        edit_message=AsyncMock(),
        start=AsyncMock(),
        disconnect=AsyncMock(),
        get_me=AsyncMock(return_value=SimpleNamespace(username="cutly_bot")),
        run_until_disconnected=AsyncMock(),
    )
    return client


@pytest.fixture
def app(monkeypatch, telegram):
    import main
    from core.upload_session import get_upload_manager

    main.CONVERSATION_STATE.clear()
    main.CONVERSATION_OBJECT.clear()
    main.USER_LIST.clear()
    main.USER_IDS.clear()
    main.LIST_VIDEO.clear()
    main.BROADCAST_DRAFTS.clear()
    main.ADMIN_LOG_CONTEXT.clear()
    for user_id in list(main.RESTORE_DRAFTS):
        main.clear_restore_draft(user_id)
    main.CHANNEL_JOIN_LIST = {}
    main.BOT_USERNAME = "cutly_bot"
    main.BROADCAST_IN_PROGRESS = False
    main.BROADCAST_CANCEL_EVENT = None
    get_upload_manager()._sessions.clear()
    monkeypatch.setattr(main, "CLIENT", telegram)
    monkeypatch.setattr(main, "STORAGE_CHANNEL_ID", -100555)
    yield main


@pytest.fixture
def event_factory(telegram):
    from telethon import types

    def make(text="", user_id=5_000_000_001, **values):
        return SimpleNamespace(
            sender_id=user_id,
            chat_id=user_id,
            raw_text=text,
            is_private=True,
            client=telegram,
            get_sender=AsyncMock(
                return_value=types.User(id=user_id, first_name="Test")
            ),
            message=SimpleNamespace(
                grouped_id=None, text=text, sticker=None, media=None
            ),
            **values,
        )

    return make
