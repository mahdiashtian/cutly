"""Per-user conversation state (the bot's finite-state machine).

Kept in the state Redis instead of a process dict, so it survives restarts and
is shared by every process. The store is deliberately dumb — a state *name*
plus a small JSON dict; mapping the name to the bot's enum is the bot's job.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis

from repositories.redis import keys

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Conversation:
    state: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class ConversationStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds if ttl_seconds > 0 else None

    async def get(self, user_id: int) -> Conversation:
        raw = await self._redis.get(keys.conversation(user_id))
        if raw is None:
            return Conversation()
        try:
            payload = json.loads(raw)
            return Conversation(state=payload.get("state"), data=dict(payload.get("data") or {}))
        except (ValueError, AttributeError, TypeError):
            log.warning("unreadable conversation for %s; starting over", user_id)
            return Conversation()

    async def set(self, user_id: int, state: str | None, data: dict[str, Any] | None = None) -> None:
        payload = json.dumps({"state": state, "data": data or {}}, ensure_ascii=False)
        await self._redis.set(keys.conversation(user_id), payload, ex=self._ttl)

    async def clear(self, user_id: int) -> None:
        await self._redis.delete(keys.conversation(user_id))
