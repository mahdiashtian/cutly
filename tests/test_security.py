"""Each test is an attack attempt that must fail."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from bot import texts
from bot.keyboards import Btn
from bot.router import Access, Router
from bot.states import State
from repositories.redis import keys
from tests.conftest import ADMIN, OWNER, VIEWER, media

STAFF = 30  # a database admin who is not the owner


async def _force_state(container, user_id: int, state: State, **data) -> None:
    """What an attacker cannot do through the bot, but a bug might allow."""
    await container.conversations.set(user_id, state.name, data)


async def _protected_link(bot) -> str:
    await bot.container.users.ensure(OWNER)
    link = await bot.container.links.create(OWNER, [media()], expires_at=None, max_downloads=None)
    await bot.container.links.set_password(link, "right")
    return link.code


async def _make_staff(container) -> None:
    await container.users.ensure(STAFF)
    await container.users.set_admin(STAFF, True)


# ---- admin panel ----
async def test_regular_user_cannot_open_the_admin_panel(bot):
    for text in ("/admin", Btn.ADD_ADMIN, Btn.STATS, Btn.RESTORE, Btn.CANCEL_BROADCAST):
        await bot.say(VIEWER, text)
    # Not even an error message: a stranger learns nothing about the panel.
    assert bot.client.texts_to(VIEWER) == []
    assert (await bot.container.conversations.get(VIEWER)).state is None


async def test_admin_states_are_useless_without_admin_rights(bot):
    await bot.container.users.ensure(VIEWER)
    # Even if a user somehow sat in an admin state, every step re-checks rights.
    await _force_state(bot.container, VIEWER, State.ADMIN_ADD)
    await bot.say(VIEWER, str(VIEWER))
    assert not await bot.container.users.is_admin(VIEWER)

    await _force_state(bot.container, VIEWER, State.BROADCAST_CONFIRM,
                       mode="copy", audience="all", channel_ref=None, message_id=1)
    await bot.say(VIEWER, Btn.SEND_NOW)
    assert bot.queue.calls == []

    await _force_state(bot.container, VIEWER, State.GLOBAL_CAPTION_TEXT)
    await bot.say(VIEWER, "spam")
    assert (await bot.container.settings_service.get()).global_caption is None


async def test_demoted_admin_loses_access_mid_flow(bot):
    await _make_staff(bot.container)
    await bot.say(STAFF, "/admin")
    await bot.say(STAFF, Btn.CAPTION_PANEL)
    await bot.say(STAFF, Btn.SET_GLOBAL_CAPTION)
    await bot.container.users.set_admin(STAFF, False)
    await bot.say(STAFF, "hijacked caption")
    assert (await bot.container.settings_service.get()).global_caption is None


async def test_only_the_owner_manages_admins_and_the_database(bot):
    await _make_staff(bot.container)
    await bot.container.users.ensure(VIEWER)
    await bot.say(STAFF, "/admin")
    for button in (Btn.ADD_ADMIN, Btn.REMOVE_ADMIN, Btn.FULL_BACKUP, Btn.DATA_BACKUP, Btn.RESTORE):
        assert await bot.say(STAFF, button) == texts.OWNER_ONLY
    assert bot.queue.calls == []
    await _force_state(bot.container, STAFF, State.ADMIN_ADD)
    await bot.say(STAFF, str(VIEWER))
    assert not await bot.container.users.is_admin(VIEWER)

    await bot.say(ADMIN, "/admin")  # the owner can
    await bot.say(ADMIN, Btn.ADD_ADMIN)
    assert await bot.say(ADMIN, str(VIEWER)) == texts.ADMIN_ADDED


def test_router_refuses_user_routes_on_admin_states():
    router = Router()
    with pytest.raises(ValueError):
        @router.state(State.ADMIN_ADD)
        async def forgot_admin(ctx): ...
    with pytest.raises(ValueError):
        @router.text("x", states={State.RESTORE_CONFIRM})
        async def also_forgot(ctx): ...

    @router.state(State.ADMIN_ADD, access=Access.OWNER)
    async def fine(ctx): ...


@dataclass
class FakeCallback:
    sender_id: int
    data: bytes
    answers: list = field(default_factory=list)
    edits: list = field(default_factory=list)

    async def answer(self, text=None, alert=False):
        self.answers.append(text)

    async def edit(self, text, buttons=None):
        self.edits.append(text)


async def test_admin_buttons_on_old_messages_are_rechecked(bot):
    await bot.container.users.ensure(VIEWER)
    tap = FakeCallback(VIEWER, f"userlog:{OWNER}:0".encode())
    await bot.dispatcher._on_callback(tap)
    assert tap.edits == [] and texts.NO_ACCESS in tap.answers


# ---- forced join cannot be skipped half-way through a flow ----
async def _require_channel(bot) -> None:
    await bot.container.channels.add(chat_ref="news", invite_link="https://t.me/news", title="News")


async def _leave_channel(bot, user_id: int) -> None:
    bot.client.members.discard(user_id)
    await bot.container.cache_redis.delete(keys.joined_channels(user_id))  # cached answer expired


async def test_leaving_the_channel_mid_flow_blocks_the_download(bot):
    code = await _protected_link(bot)
    await _require_channel(bot)
    bot.client.members = {OWNER, VIEWER}
    assert await bot.say(VIEWER, f"/start get_{code}") == texts.ASK_LINK_PASSWORD
    await _leave_channel(bot, VIEWER)
    assert await bot.say(VIEWER, "right") == texts.NEED_JOIN
    assert not any(m.file is not None for m in bot.client.sent if m.chat_id == VIEWER)


async def test_album_upload_requires_membership(bot):
    await _require_channel(bot)
    bot.client.members = {OWNER}
    await bot.say(OWNER, Btn.UPLOAD)
    await _leave_channel(bot, OWNER)

    class Album:
        sender_id, is_private, messages = OWNER, True, [type("M", (), {"media": "photo", "id": 1})()]

        async def get_sender(self):
            return None

    await bot.dispatcher._on_album(Album())
    assert await bot.container.uploads.items(OWNER) == []


async def test_history_buttons_require_membership(bot):
    await _require_channel(bot)
    bot.client.members = set()
    await bot.container.users.ensure(VIEWER)
    tap = FakeCallback(VIEWER, b"hist:0")
    await bot.dispatcher._on_callback(tap)
    assert tap.edits == []


# ---- brute force and flooding ----
async def test_link_password_cannot_be_brute_forced(bot):
    code = await _protected_link(bot)
    await bot.say(VIEWER, f"/start get_{code}")
    limit = bot.container.password_limiter.limit
    for _ in range(limit):
        assert await bot.say(VIEWER, "wrong") == texts.WRONG_PASSWORD
    await bot.say(VIEWER, f"/start get_{code}")
    assert await bot.say(VIEWER, "right") == texts.TOO_MANY_ATTEMPTS  # even the right one, for now
    assert not any(m.file is not None for m in bot.client.sent if m.chat_id == VIEWER)


async def test_flooding_user_is_cut_off_with_one_notice(bot):
    limit = bot.container.flood_limiter.limit
    for _ in range(limit):
        await bot.say(VIEWER, "hi")
    before = len(bot.client.texts_to(VIEWER))
    for _ in range(5):
        await bot.say(VIEWER, "hi")
    assert bot.client.texts_to(VIEWER)[before:] == [texts.TOO_FAST]


# ---- input validation ----
async def test_malformed_codes_never_reach_cache_or_database(bot):
    for payload in ("../../etc", "a" * 40, "x y", "<script>", "get_"):
        await bot.container.flood_limiter.reset(VIEWER)
        assert await bot.say(VIEWER, f"/start get_{payload}") == texts.LINK_NOT_FOUND
    cached = [key async for key in bot.container.cache_redis.scan_iter(match=keys.link("*"))]
    assert cached == []


async def test_unknown_codes_are_cached_only_briefly(bot):
    await bot.container.links.get("Unknown1")
    ttl = await bot.container.cache_redis.ttl(keys.link("Unknown1"))
    assert 0 < ttl <= 300


async def test_upload_cap_holds_under_concurrency(container):
    await container.uploads.start(OWNER)
    results = await asyncio.gather(*(container.uploads.add(OWNER, [media()], limit=10) for _ in range(30)))
    assert sum(result is not None for result in results) == 10
    assert len(await container.uploads.items(OWNER)) == 10


async def test_overlong_password_is_rejected(bot):
    await bot.container.users.ensure(OWNER)
    link = await bot.container.links.create(OWNER, [media()], expires_at=None, max_downloads=None)
    await bot.say(OWNER, Btn.SET_PASSWORD)
    await bot.say(OWNER, link.code)
    reply = await bot.say(OWNER, "x" * 500)
    assert reply == texts.PASSWORD_TOO_LONG.format(limit=128)
    assert (await bot.container.links.get(link.code)).password_hash is None


def test_celery_accepts_json_only():
    from worker.app import celery_app

    assert celery_app.conf.accept_content == ["json"] and celery_app.conf.task_serializer == "json"
