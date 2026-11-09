"""Cache primitives shared by every Redis cache repository.

Read contract (the same as couplyo's):

* a hit returns the value;
* a *negative* hit returns ``None`` — the row is known not to exist, so random
  or deleted share codes do not hammer the database;
* a miss raises :class:`CacheMiss`, and so does any payload that no longer
  matches the DTO (old deploy, wrong type): SQL stays the source of truth and
  the normal cache-aside path overwrites the bad entry.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import NoReturn, TypeVar

from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from schemas.base import BaseDTO

T = TypeVar("T", bound=BaseDTO)
R = TypeVar("R")
log = logging.getLogger(__name__)

NEGATIVE_MARKER = "\x00absent"


class CacheMiss(Exception):
    """The key is absent or unusable; read the database instead."""


class RedisCache:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds if ttl_seconds > 0 else None

    def _invalid(self, key: str, what: str) -> NoReturn:
        log.warning("unusable cached %s at %s; treating as a miss", what, key)
        raise CacheMiss(key)

    async def _read(self, key: str, operation: Awaitable[R]) -> R:
        """A wrong Redis type or encoding is stale cache, not an outage."""
        try:
            return await operation
        except ResponseError as error:
            if not str(error).startswith("WRONGTYPE"):
                raise
            self._invalid(key, "redis type")
        except UnicodeError:
            self._invalid(key, "encoding")

    async def _get_raw(self, key: str) -> str:
        raw = await self._read(key, self._redis.get(key))
        if raw is None:
            raise CacheMiss(key)
        return raw

    async def _get_model(self, key: str, model: type[T]) -> T | None:
        raw = await self._get_raw(key)
        if raw == NEGATIVE_MARKER:
            return None
        try:
            return model.model_validate_json(raw)
        except ValidationError:
            self._invalid(key, model.__name__)

    async def _set_model(self, key: str, value: BaseDTO | None, *, ttl: int | None = None) -> None:
        payload = NEGATIVE_MARKER if value is None else value.model_dump_json()
        await self._redis.set(key, payload, ex=ttl or self._ttl)

    async def _get_list(self, key: str, adapter: TypeAdapter[list[T]]) -> list[T]:
        raw = await self._get_raw(key)
        try:
            return adapter.validate_json(raw)
        except ValidationError:
            self._invalid(key, "list")

    async def _set_list(self, key: str, items: list[T], adapter: TypeAdapter[list[T]]) -> None:
        await self._redis.set(key, adapter.dump_json(items), ex=self._ttl)

    async def _delete(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*keys)


async def delete_matching(redis: Redis, pattern: str, *, batch: int = 500) -> int:
    """Delete keys by pattern with SCAN + UNLINK: never the blocking KEYS command,
    and never another application's keys."""
    deleted, keys = 0, []
    async for key in redis.scan_iter(match=pattern, count=batch):
        keys.append(key)
        if len(keys) >= batch:
            deleted += await redis.unlink(*keys)
            keys.clear()
    if keys:
        deleted += await redis.unlink(*keys)
    return deleted
