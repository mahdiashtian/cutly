"""Shared fixtures: a real Container on in-memory SQLite + fakeredis, and fakes
for the few Telegram calls the tests exercise. Nothing touches the network."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.update(API_ID="1", API_HASH="test", BOT_TOKEN="1:test", ENVIRONMENT="test")

from bot.app import BotApp  # noqa: E402
from bot.dispatcher import Dispatcher  # noqa: E402
from bot.handlers import build_router, upload  # noqa: E402
from bot.media import MediaRef  # noqa: E402
from container import Container  # noqa: E402
from core.config import Settings  # noqa: E402
from core.enums import MediaType  # noqa: E402
from schemas.link import MediaItem  # noqa: E402


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = dict(
        environment="test", api_id=1, api_hash="test", bot_token="1:test",
        db_url="sqlite+aiosqlite:///:memory:", backup_dir=tmp_path / "backup",
        admin_master=1, storage_channel_id=-100500, broadcast_rate_per_second=1000,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
async def container(tmp_path: Path):
    container = Container(make_settings(tmp_path))
    await container.startup()
    await container.database.create_all()
    yield container
    await container.shutdown()


_ids = count(1000)


def media(media_type: MediaType = MediaType.PHOTO, size: int = 1024) -> MediaItem:
    file_id = next(_ids)
    return MediaItem(media_type=media_type, size=size, tg_file_id=file_id, tg_access_hash=-file_id,
                     tg_file_reference=b"\x00ref" + bytes([file_id % 256]), storage_message_id=file_id)


@dataclass
class SentMessage:
    id: int
    chat_id: int
    text: str = ""
    buttons: object = None
    file: object = None


@dataclass
class FakeClient:
    """Records what the bot sends; behaves like the few TelegramClient methods used."""

    sent: list[SentMessage] = field(default_factory=list)
    edits: list[tuple[int, str]] = field(default_factory=list)
    forwarded: list[tuple[object, object]] = field(default_factory=list)
    fail_for: dict[int, Exception] = field(default_factory=dict)
    # Users who are members of every mandatory channel (None: everybody is).
    members: set[int] | None = None
    _ids: count = field(default_factory=lambda: count(1))

    async def get_permissions(self, channel, user_id):
        if self.members is not None and user_id not in self.members:
            from telethon.errors import UserNotParticipantError

            raise UserNotParticipantError(request=None)
        return object()

    def _record(self, chat, **kwargs) -> SentMessage:
        chat_id = getattr(chat, "user_id", chat)
        if chat_id in self.fail_for:
            raise self.fail_for.pop(chat_id)
        message = SentMessage(id=next(self._ids), chat_id=chat_id, **kwargs)
        self.sent.append(message)
        return message

    async def send_message(self, chat, text="", buttons=None, **_):
        return self._record(chat, text=text if isinstance(text, str) else "<copy>", buttons=buttons)

    async def send_file(self, chat, file, caption=None, buttons=None, **_):
        if isinstance(file, list):
            return [self._record(chat, text=c, file=f) for f, c in zip(file, caption, strict=True)]
        return self._record(chat, text=caption or "", file=file, buttons=buttons)

    async def forward_messages(self, chat, messages, from_peer=None):
        self.forwarded.append((chat, messages))
        if isinstance(messages, list):
            return [SentMessage(id=next(self._ids), chat_id=chat) for _ in messages]
        return self._record(chat, text="<forward>")

    async def edit_message(self, chat, message_id, text):
        self.edits.append((message_id, text))

    async def get_messages(self, chat, ids=None):
        return SentMessage(id=ids, chat_id=chat, text="source")

    def texts_to(self, chat_id: int) -> list[str]:
        return [message.text for message in self.sent if message.chat_id == chat_id]


# ---- the whole bot (dispatcher + router + services) with Telegram faked ----
OWNER, VIEWER, ADMIN = 10, 20, 1  # ADMIN is ADMIN_MASTER in make_settings()


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

    return SimpleNamespace(app=app, client=client, queue=queue, say=say, container=container,
                           dispatcher=dispatcher)


