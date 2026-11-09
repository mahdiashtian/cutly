"""End-to-end handler flows through the real dispatcher, router and services,
with Telegram replaced by a recording fake."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from bot import texts
from bot.app import BotApp
from bot.dispatcher import Dispatcher
from bot.handlers import build_router, upload
from bot.keyboards import Btn
from bot.media import MediaRef
from bot.states import State
from core.enums import MediaType
from tests.conftest import FakeClient

OWNER, VIEWER, ADMIN = 10, 20, 1


@dataclass
class RecordingQueue:
    calls: list[tuple] = field(default_factory=list)

    def __getattr__(self, name):
        async def record(*args):
            self.calls.append((name, *args))
        return record


@dataclass
class FakeEvent:
    sender_id: int
    raw_text: str = ""
    message: SimpleNamespace = None
    is_private: bool = True

    async def get_sender(self):
        return SimpleNamespace(first_name="Ali", username="ali")


def message(message_id=1, media=None):
    return SimpleNamespace(id=message_id, grouped_id=None, media=media, input_sender=None, document=None)


@pytest.fixture
def bot(container, monkeypatch):
    client, queue = FakeClient(), RecordingQueue()
    app = BotApp(container, client, queue, username="cutly_bot")
    dispatcher = Dispatcher(app, build_router())
    refs = iter(range(500, 600))
    monkeypatch.setattr(upload, "extract_media", lambda msg: msg.media and MediaRef(
        MediaType.PHOTO, 2048, next(refs), 1, b"ref"))

    async def say(user_id: int, text: str = "", media=None):
        await dispatcher._handle_message(FakeEvent(user_id, text, message(media=media)))
        return client.texts_to(user_id)[-1] if client.texts_to(user_id) else None

    return SimpleNamespace(app=app, client=client, queue=queue, say=say, container=container)


async def _state(container, user_id):
    return (await container.conversations.get(user_id)).state


async def _upload_link(bot, limits="-  2"):
    await bot.say(OWNER, Btn.UPLOAD)
    reply = await bot.say(OWNER, media="photo")
    assert reply.startswith("✅ فایل شما ذخیره شد! (1 فایل)")
    await bot.say(OWNER, media="photo")
    await bot.say(OWNER, Btn.FINISH_UPLOAD)
    assert await _state(bot.container, OWNER) == State.UPLOAD_LIMITS.name
    done = await bot.say(OWNER, limits)
    assert "https://t.me/cutly_bot?start=get_" in done
    return done.split("start=get_")[1].split()[0]


async def test_upload_then_download_with_limit(bot):
    code = await _upload_link(bot)
    link = await bot.container.links.get(code)
    assert len(link.media) == 2 and link.max_downloads == 2 and link.expires_at is None

    await bot.say(VIEWER, f"/start get_{code}")
    sent = [m for m in bot.client.sent if m.chat_id == VIEWER and m.file is not None]
    assert len(sent) == 2 and "👁 تعداد دانلود : 1" in sent[0].text  # one album of two
    assert bot.queue.calls[-1] == ("delete_messages_later", VIEWER, [m.id for m in sent], 30)

    await bot.say(VIEWER, f"/start get_{code}")
    assert await bot.say(VIEWER, f"/start get_{code}") == texts.LINK_EXHAUSTED


async def test_password_protected_link(bot):
    code = await _upload_link(bot, limits="7 -")
    await bot.say(OWNER, Btn.SET_PASSWORD)
    await bot.say(OWNER, code)
    assert await bot.say(OWNER, "pw") == texts.PASSWORD_SET

    assert await bot.say(VIEWER, f"/start get_{code}") == texts.ASK_LINK_PASSWORD
    assert await bot.say(VIEWER, "nope") == texts.WRONG_PASSWORD
    await bot.say(VIEWER, "pw")
    assert any(m.file is not None for m in bot.client.sent if m.chat_id == VIEWER)
    assert await _state(bot.container, VIEWER) is None  # back to idle


async def test_management_requires_ownership(bot):
    code = await _upload_link(bot)
    await bot.say(VIEWER, Btn.DELETE)
    assert await bot.say(VIEWER, code) == texts.LINK_NOT_FOUND_RETRY
    await bot.say(OWNER, Btn.DELETE)
    assert await bot.say(OWNER, code) == texts.DELETED
    assert await bot.container.links.get(code) is None


async def test_state_scoped_labels_are_not_taken_as_input(bot):
    await bot.say(OWNER, Btn.SET_CAPTION)
    before = len(bot.client.sent)
    await bot.say(OWNER, Btn.STATS)  # an admin-panel label while we wait for a code
    assert len(bot.client.sent) == before
    assert await _state(bot.container, OWNER) == State.CAPTION_CODE.name


async def test_admin_only_routes_ignore_regular_users(bot):
    await bot.say(VIEWER, "/admin")
    assert await _state(bot.container, VIEWER) is None
    await bot.say(ADMIN, "/admin")
    assert await _state(bot.container, ADMIN) == State.ADMIN_PANEL.name
    stats = await bot.say(ADMIN, Btn.STATS)
    assert stats.startswith("📊 آمار ربات")


async def test_back_returns_to_the_parent_menu(bot):
    await bot.say(ADMIN, "/admin")
    await bot.say(ADMIN, Btn.JOIN_PANEL)
    await bot.say(ADMIN, Btn.ADD_CHANNEL)
    assert await _state(bot.container, ADMIN) == State.CHANNEL_ADD.name
    await bot.say(ADMIN, Btn.BACK)
    assert await _state(bot.container, ADMIN) == State.JOIN_PANEL.name
    await bot.say(ADMIN, Btn.BACK)
    assert await _state(bot.container, ADMIN) == State.ADMIN_PANEL.name


async def test_broadcast_draft_is_queued_for_the_worker(bot):
    await bot.container.users.ensure(VIEWER)
    await bot.say(ADMIN, "/admin")
    await bot.say(ADMIN, Btn.COPY_ALL)
    await bot.say(ADMIN, "hello everyone")
    await bot.say(ADMIN, Btn.AUDIENCE_ALL)
    assert await _state(bot.container, ADMIN) == State.BROADCAST_CONFIRM.name
    await bot.say(ADMIN, Btn.SEND_NOW)
    name, broadcast_id = bot.queue.calls[-1]
    broadcast = await bot.container.broadcasts.get(broadcast_id)
    assert name == "run_broadcast" and broadcast.audience == "all" and broadcast.source_message_id == 1


async def test_maintenance_mode_blocks_messages(bot):
    await bot.container.maintenance.turn_on()
    assert await bot.say(OWNER, "/start") == texts.MAINTENANCE
