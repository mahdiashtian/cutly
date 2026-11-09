"""A validated backup waiting for the admin's confirmation."""
from __future__ import annotations

from redis.asyncio import Redis

from repositories.redis import keys
from schemas.base import BaseDTO

STAGED_RESTORE_TTL_SECONDS = 30 * 60


class StagedRestore(BaseDTO):
    staging_path: str
    revision: str
    counts: dict[str, int]


class StagedRestoreStore:
    """Written by the worker that validated the file, read by the bot when the
    admin confirms; it expires after 30 minutes like the old in-memory draft."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def put(self, admin_id: int, staged: StagedRestore) -> None:
        await self._redis.set(keys.staged_restore(admin_id), staged.model_dump_json(),
                              ex=STAGED_RESTORE_TTL_SECONDS)

    async def pop(self, admin_id: int) -> StagedRestore | None:
        raw = await self._redis.getdel(keys.staged_restore(admin_id))
        return StagedRestore.model_validate_json(raw) if raw else None
