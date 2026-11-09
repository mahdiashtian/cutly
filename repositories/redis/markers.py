"""Small Redis markers that are not copies of SQL rows."""
from __future__ import annotations

from redis.asyncio import Redis

from repositories.redis import keys


class ActivityThrottle:
    """Lets ``last_active_at`` be written at most once per window per user.

    ``SET NX EX`` is atomic, so of many concurrent messages exactly one wins
    the right to write — turning one SQL UPDATE per message into one per window.
    """

    def __init__(self, redis: Redis, *, window_seconds: int) -> None:
        self._redis = redis
        self._window = max(1, window_seconds)

    async def should_touch(self, user_id: int) -> bool:
        return bool(await self._redis.set(keys.activity_touch(user_id), "1", nx=True, ex=self._window))


class JoinedChannelsMarker:
    """Caches only the *positive* answer "is in every mandatory channel".

    Caching "not joined" would keep a user who just joined locked out until it
    expired. The stored value is the channel-set fingerprint, so changing the
    mandatory channels invalidates every marker without scanning for them.
    """

    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = max(1, ttl_seconds)

    async def is_marked(self, user_id: int, fingerprint: str) -> bool:
        return await self._redis.get(keys.joined_channels(user_id)) == fingerprint

    async def mark(self, user_id: int, fingerprint: str) -> None:
        await self._redis.set(keys.joined_channels(user_id), fingerprint, ex=self._ttl)


class MaintenanceFlag:
    """Raised while a restore replaces the data; every process honours it."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def is_on(self) -> bool:
        return bool(await self._redis.exists(keys.maintenance()))

    async def turn_on(self, *, ttl_seconds: int = 3600) -> None:
        # The TTL is a safety net: a crashed restore cannot lock the bot forever.
        await self._redis.set(keys.maintenance(), "1", ex=ttl_seconds)

    async def turn_off(self) -> None:
        await self._redis.delete(keys.maintenance())
