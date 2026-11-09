"""Routing table for private messages, albums and inline buttons.

The old code registered ~60 Telethon handlers, each with a filter chain that
re-read the user's state. Here the dispatcher loads the state *once* and the
router resolves the handler with two dictionary lookups:

1. the message text (a button label or ``/command``), optionally restricted to
   some states — e.g. «✅ اتمام ارسال فایل» only means something while uploading;
2. otherwise the handler of the current state — e.g. "the text typed while we
   asked for a caption".
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from telethon import events
from telethon.tl.custom import Message

from bot.states import State

if TYPE_CHECKING:
    from bot.app import BotApp


@dataclass
class Context:
    """Everything a message handler needs, and nothing it has to look up again."""

    app: BotApp
    event: events.NewMessage.Event
    state: State
    data: dict[str, Any]
    args: str = ""  # the text after a /command

    @property
    def user_id(self) -> int:
        return self.event.sender_id

    @property
    def message(self) -> Message:
        return self.event.message

    @property
    def text(self) -> str:
        return (self.event.raw_text or "").strip()

    async def reply(self, text: str, buttons=None, **kwargs) -> Message:
        return await self.app.client.send_message(self.user_id, text, buttons=buttons, **kwargs)

    async def go(self, state: State, **data: Any) -> None:
        """Move to ``state``; ``data`` replaces the conversation's data."""
        self.state, self.data = state, data
        if state is State.IDLE and not data:
            await self.app.container.conversations.clear(self.user_id)
        else:
            await self.app.container.conversations.set(self.user_id, state.name, data)

    async def first_name(self) -> str:
        sender = await self.event.get_sender()
        return getattr(sender, "first_name", None) or getattr(sender, "username", None) or "کاربر"


@dataclass
class CallbackContext:
    app: BotApp
    event: events.CallbackQuery.Event
    args: list[str]

    @property
    def user_id(self) -> int:
        return self.event.sender_id


Handler = Callable[[Context], Awaitable[None]]
AlbumHandler = Callable[[Context, list[Message]], Awaitable[None]]
CallbackHandler = Callable[[CallbackContext], Awaitable[None]]


@dataclass(frozen=True)
class Route:
    handler: Handler
    admin: bool = False
    require_join: bool = False
    states: frozenset[State] | None = None  # None: valid in every state

    def accepts(self, state: State) -> bool:
        return self.states is None or state in self.states


@dataclass(frozen=True)
class CallbackRoute:
    handler: CallbackHandler
    admin: bool = False


@dataclass
class Router:
    texts: dict[str, list[Route]] = field(default_factory=dict)
    states: dict[State, Route] = field(default_factory=dict)
    albums: dict[State, AlbumHandler] = field(default_factory=dict)
    callbacks: dict[str, CallbackRoute] = field(default_factory=dict)

    # ---- registration (decorators) ----
    def text(self, *labels: str, admin: bool = False, join: bool = False,
             states: set[State] | frozenset[State] | None = None):
        def register(handler: Handler) -> Handler:
            route = Route(handler, admin, join, frozenset(states) if states else None)
            for label in labels:
                # State-scoped routes are tried before global ones.
                routes = self.texts.setdefault(label, [])
                routes.insert(0 if route.states else len(routes), route)
            return handler
        return register

    def state(self, state: State, *, admin: bool = False, join: bool = False):
        def register(handler: Handler) -> Handler:
            if state in self.states:
                raise ValueError(f"{state} already has a handler")
            self.states[state] = Route(handler, admin, join)
            return handler
        return register

    def album(self, state: State):
        def register(handler: AlbumHandler) -> AlbumHandler:
            self.albums[state] = handler
            return handler
        return register

    def callback(self, prefix: str, *, admin: bool = False):
        def register(handler: CallbackHandler) -> CallbackHandler:
            self.callbacks[prefix] = CallbackRoute(handler, admin)
            return handler
        return register

    def include(self, other: Router) -> None:
        for label, routes in other.texts.items():
            for route in routes:
                existing = self.texts.setdefault(label, [])
                existing.insert(0 if route.states else len(existing), route)
        for state, route in other.states.items():
            if state in self.states:
                raise ValueError(f"{state} already has a handler")
            self.states[state] = route
        self.albums.update(other.albums)
        self.callbacks.update(other.callbacks)

    # ---- resolution ----
    def resolve(self, key: str, state: State) -> Route | None:
        """The text route for ``key`` in ``state``, else the state's own route.

        A known label that is not valid in this state resolves to ``None`` (the
        message is ignored), exactly like the old filters: typing «📈آمار» while
        we wait for a caption must not become the caption.
        """
        routes = self.texts.get(key)
        if routes is not None:
            return next((route for route in routes if route.accepts(state)), None)
        return self.states.get(state)
