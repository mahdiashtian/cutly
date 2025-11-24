"""Custom Telethon filter helpers."""

from __future__ import annotations

import inspect
from enum import Enum
from typing import Awaitable, Callable, Dict, Optional, Union

from telethon import events

from services.user import read_user_from_db

Predicate = Callable[[events.NewMessage.Event], Union[Awaitable[bool], bool]]


def conversation(conversation_state: Dict[int, Optional[Enum]], state: Optional[Enum]) -> Predicate:
    """Return a predicate that enforces a given conversation state.

    Args:
        conversation_state: Runtime store of user state keyed by Telegram user ID.
        state: The desired state value. Pass ``None`` to match idle users.

    Returns:
        An awaitable predicate compatible with ``events.NewMessage``.
        
    Examples:
        >>> state_dict = {}
        >>> predicate = conversation(state_dict, None)
    """

    async def _predicate(event: events.NewMessage.Event) -> bool:
        return conversation_state.get(event.sender_id) == state

    return _predicate


def admin_filter(admin_master: int) -> Predicate:
    """Return a predicate that authorizes privileged users.

    Args:
        admin_master: Telegram user ID with unconditional access.

    Returns:
        Awaitable predicate that resolves to ``True`` for admins.
        
    Examples:
        >>> predicate = admin_filter(12345678)
    """

    async def _predicate(event: events.NewMessage.Event) -> bool:
        if event.sender_id == admin_master:
            return True
        user = await read_user_from_db(event.sender_id)
        return bool(user and (user.is_superuser or user.is_staff))

    return _predicate


def private_only() -> Predicate:
    """Return a predicate that only accepts private messages (PV).
    
    Blocks messages from groups, channels, and supergroups.
    Bot should only respond to private 1-on-1 conversations.
    
    Returns:
        Awaitable predicate that resolves to ``True`` only for private messages.
        
    Examples:
        >>> predicate = private_only()
        >>> # Use in event handler: func=private_only()
    """
    
    async def _predicate(event: events.NewMessage.Event) -> bool:
        return event.is_private

    return _predicate


def compose_filters(*predicates: Predicate) -> Predicate:
    """Combine multiple predicates into one Telethon-compatible function.
    
    Args:
        *predicates: Variable number of predicate functions.
        
    Returns:
        Combined predicate function.
        
    Examples:
        >>> pred1 = conversation({}, None)
        >>> pred2 = admin_filter(12345678)
        >>> combined = compose_filters(pred1, pred2)
    """

    async def _predicate(event: events.NewMessage.Event) -> bool:
        for predicate in predicates:
            result = predicate(event)
            if inspect.isawaitable(result):
                result = await result
            if not result:
                return False
        return True

    return _predicate
