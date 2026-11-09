"""Turns Telethon updates into handler calls.

Per private message: maintenance check -> load the conversation once -> resolve
a route -> make sure the user exists (and record activity) -> admin / forced
join checks -> call the handler. Telethon runs each update in its own task, so a
slow handler never delays other users.
"""
from __future__ import annotations

import contextlib
import logging

from telethon import events

from bot import texts
from bot.app import BotApp
from bot.membership import MembershipGuard, join_buttons
from bot.router import CallbackContext, Context, Route, Router
from bot.states import State

log = logging.getLogger(__name__)


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

    # ---- messages ----
    async def _on_message(self, event: events.NewMessage.Event) -> None:
        try:
            await self._handle_message(event)
        except Exception:  # noqa: BLE001 - one failing update must not kill the loop
            log.exception("message handler failed for user %s", event.sender_id)
            await self._safe_reply(event.sender_id, texts.UNEXPECTED_ERROR)

    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        container = self._app.container
        if await container.maintenance.is_on():
            await self._app.client.send_message(event.sender_id, texts.MAINTENANCE)
            return
        conversation = await container.conversations.get(event.sender_id)
        state = _to_state(conversation.state)
        if event.message.grouped_id and state is State.UPLOADING:
            return  # each album item also arrives here; the Album handler takes them together

        text = (event.raw_text or "").strip()
        key, _, args = text.partition(" ") if text.startswith("/") else (text, "", "")
        if key.startswith("/") and key not in self._router.texts:
            return  # unknown command: never treat it as input for the current state
        route = self._router.resolve(key, state)
        if route is None:
            return

        context = Context(self._app, event, state, conversation.data, args.strip())
        if await self._authorised(context, route):
            await route.handler(context)

    async def _authorised(self, context: Context, route: Route) -> bool:
        input_sender = context.message.input_sender
        await self._app.container.users.ensure(context.user_id, getattr(input_sender, "access_hash", None))
        if route.admin and not await self._app.is_admin(context.user_id):
            return False
        if route.require_join:
            missing = await self._membership.missing_channels(context.user_id)
            if missing:
                payload = context.args if context.args.startswith("get_") else ""
                await context.reply(texts.NEED_JOIN, buttons=join_buttons(missing, self._app.username, payload))
                return False
        return True

    # ---- albums ----
    async def _on_album(self, event: events.Album.Event) -> None:
        try:
            container = self._app.container
            if await container.maintenance.is_on():
                return
            conversation = await container.conversations.get(event.sender_id)
            state = _to_state(conversation.state)
            handler = self._router.albums.get(state)
            if handler is None:
                return
            await container.users.ensure(event.sender_id)
            await handler(Context(self._app, event, state, conversation.data), list(event.messages))
        except Exception:  # noqa: BLE001
            log.exception("album handler failed for user %s", event.sender_id)
            await self._safe_reply(event.sender_id, texts.UNEXPECTED_ERROR)

    # ---- inline buttons ----
    async def _on_callback(self, event: events.CallbackQuery.Event) -> None:
        try:
            prefix, *args = event.data.decode(errors="replace").split(":")
            route = self._router.callbacks.get(prefix)
            if route is None or await self._app.container.maintenance.is_on():
                await event.answer()
                return
            # Inline keyboards live forever on old messages: re-check rights on every tap.
            if route.admin and not await self._app.is_admin(event.sender_id):
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
