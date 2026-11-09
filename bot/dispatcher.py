"""Turns Telethon updates into handler calls.

Every update — message, album or button tap — goes through the same gate:
maintenance check -> per-user flood limit -> make sure the user exists ->
access check (owner / admin / forced join) -> handler. Telethon runs each update
in its own task, so a slow handler never delays other users.
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable

from telethon import events

from bot import texts
from bot.app import BotApp
from bot.membership import MembershipGuard, join_buttons
from bot.router import Access, CallbackContext, Context, Router
from bot.states import State

log = logging.getLogger(__name__)
Notify = Callable[[str], Awaitable[object]]


def _to_state(name: str | None) -> State:
    try:
        return State[name] if name else State.IDLE
    except KeyError:  # a state removed in a newer release
        return State.IDLE


class Dispatcher:
    def __init__(self, app: BotApp, router: Router) -> None:
        self._app = app
        self._router = router
        self._membership = MembershipGuard(app.container, app.client)

    def register(self) -> None:
        client = self._app.client
        client.add_event_handler(self._on_message, events.NewMessage(incoming=True, func=lambda e: e.is_private))
        client.add_event_handler(self._on_album, events.Album(func=lambda e: e.is_private))
        client.add_event_handler(self._on_callback, events.CallbackQuery())

    # ---- the shared gate ----
    async def _flooding(self, user_id: int, notify: Notify) -> bool:
        """True when this user exceeded the per-user rate; they are told once."""
        limiter = self._app.container.flood_limiter
        count = await limiter.hit(user_id)
        if count == limiter.limit + 1:
            await notify(texts.TOO_FAST)
        return count > limiter.limit

    async def _allowed(self, user_id: int, access: Access, notify: Notify, start_payload: str = "") -> bool:
        app = self._app
        if access is Access.OWNER:
            if app.container.users.is_owner(user_id):
                return True
            if await app.is_admin(user_id):  # strangers learn nothing about the panel
                await notify(texts.OWNER_ONLY)
            return False
        if access is Access.ADMIN:
            return await app.is_admin(user_id)
        missing = await self._membership.missing_channels(user_id)
        if missing:
            await app.client.send_message(
                user_id, texts.NEED_JOIN, buttons=join_buttons(missing, app.username, start_payload)
            )
            return False
        return True

    def _notify(self, user_id: int) -> Notify:
        return lambda text: self._app.client.send_message(user_id, text)

    # ---- messages ----
    async def _on_message(self, event: events.NewMessage.Event) -> None:
        try:
            await self._handle_message(event)
        except Exception:  # noqa: BLE001 - one failing update must not kill the loop
            log.exception("message handler failed for user %s", event.sender_id)
            await self._safe_reply(event.sender_id, texts.UNEXPECTED_ERROR)

    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        container, user_id = self._app.container, event.sender_id
        if await container.maintenance.is_on():
            await self._app.client.send_message(user_id, texts.MAINTENANCE)
            return
        conversation = await container.conversations.get(user_id)
        state = _to_state(conversation.state)
        if event.message.grouped_id and state is State.UPLOADING:
            return  # each album item also arrives here; the Album handler takes them together
        if await self._flooding(user_id, self._notify(user_id)):
            return

        text = (event.raw_text or "").strip()
        key, _, args = text.partition(" ") if text.startswith("/") else (text, "", "")
        if key.startswith("/") and key not in self._router.texts:
            return  # unknown command: never treat it as input for the current state
        route = self._router.resolve(key, state)
        if route is None:
            return

        context = Context(self._app, event, state, conversation.data, args.strip())
        input_sender = event.message.input_sender
        await container.users.ensure(user_id, getattr(input_sender, "access_hash", None))
        payload = context.args if context.args.startswith("get_") else ""
        if await self._allowed(user_id, route.access, self._notify(user_id), payload):
            await route.handler(context)

    # ---- albums ----
    async def _on_album(self, event: events.Album.Event) -> None:
        try:
            container, user_id = self._app.container, event.sender_id
            if await container.maintenance.is_on():
                return
            conversation = await container.conversations.get(user_id)
            state = _to_state(conversation.state)
            handler = self._router.albums.get(state)
            if handler is None or await self._flooding(user_id, self._notify(user_id)):
                return
            await container.users.ensure(user_id)
            if await self._allowed(user_id, Access.USER, self._notify(user_id)):
                await handler(Context(self._app, event, state, conversation.data), list(event.messages))
        except Exception:  # noqa: BLE001
            log.exception("album handler failed for user %s", event.sender_id)
            await self._safe_reply(event.sender_id, texts.UNEXPECTED_ERROR)

    # ---- inline buttons ----
    async def _on_callback(self, event: events.CallbackQuery.Event) -> None:
        try:
            user_id = event.sender_id
            prefix, *args = event.data.decode(errors="replace").split(":")
            route = self._router.callbacks.get(prefix)
            if route is None or await self._app.container.maintenance.is_on():
                await event.answer()
                return

            async def notify(text: str):
                return await event.answer(text, alert=True)

            if await self._flooding(user_id, notify):
                return
            await self._app.container.users.ensure(user_id)
            # Inline keyboards live forever on old messages: re-check rights on every tap.
            if not await self._allowed(user_id, route.access, notify):
                with contextlib.suppress(Exception):
                    await event.answer(texts.NO_ACCESS, alert=True)
                return
            await route.handler(CallbackContext(self._app, event, args))
        except Exception:  # noqa: BLE001
            log.exception("callback handler failed for user %s", event.sender_id)
            # The query may already be answered or expired.
            with contextlib.suppress(Exception):
                await event.answer(texts.UNEXPECTED_ERROR, alert=True)

    async def _safe_reply(self, user_id: int, text: str) -> None:
        try:
            await self._app.client.send_message(user_id, text)
        except Exception:  # noqa: BLE001
            log.warning("could not notify user %s", user_id, exc_info=True)
