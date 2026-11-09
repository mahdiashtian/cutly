"""A user's in-progress upload: the media collected before a link is created."""
from __future__ import annotations

from redis.asyncio import Redis

from repositories.redis import keys
from schemas.link import MediaItem


class UploadSessionStore:
    """A Redis LIST per user.

    Several files sent quickly are handled concurrently; ``RPUSH`` appends
    atomically, so none of them is lost (a read-modify-write of a JSON blob
    would drop all but one). The list survives restarts and is visible to every
    process; the TTL removes abandoned sessions.
    """

    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def start(self, user_id: int) -> None:
        await self._redis.delete(keys.upload_session(user_id))

    async def add(self, user_id: int, items: list[MediaItem], *, limit: int) -> int | None:
        """Append items; return the new size, or ``None`` if that would exceed ``limit``.

        Checking before appending would race with a concurrent upload, so the
        items are appended first and, if the list grew past the limit, trimmed
        back. RPUSH puts them at the tail, so exactly the overflow is removed.
        """
        key = keys.upload_session(user_id)
        pipe = self._redis.pipeline(transaction=True)
        pipe.rpush(key, *(item.model_dump_json() for item in items))
        pipe.expire(key, self._ttl)
        size, _ = await pipe.execute()
        if size > limit:
            await self._redis.ltrim(key, 0, limit - 1)
            return None
        return int(size)

    async def items(self, user_id: int) -> list[MediaItem]:
        raw = await self._redis.lrange(keys.upload_session(user_id), 0, -1)
        return [MediaItem.model_validate_json(item) for item in raw]

    async def clear(self, user_id: int) -> None:
        await self._redis.delete(keys.upload_session(user_id))
