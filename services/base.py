"""Cache-aside helpers shared by services."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from redis.exceptions import RedisError

from repositories.postgres.unit_of_work import UnitOfWorkFactory
from repositories.redis.base import CacheMiss

R = TypeVar("R")


class Service:
    """Base for services: owns the Unit-of-Work factory and the cache helpers.

    A Redis failure never fails a request. A failed read falls back to SQL; a
    failed write is logged and ignored (the TTL bounds how long it matters).
    """

    def __init__(self, uow: UnitOfWorkFactory) -> None:
        self._uow = uow
        self._log = logging.getLogger(type(self).__module__)

    async def _cached(
        self,
        *,
        read_cache: Callable[[], Awaitable[R]],
        read_db: Callable[[], Awaitable[R]],
        write_cache: Callable[[R], Awaitable[None]],
    ) -> R:
        try:
            return await read_cache()
        except CacheMiss:
            pass
        except RedisError:
            self._log.warning("cache read failed; using the database", exc_info=True)
            return await read_db()
        value = await read_db()
        await self._safe(write_cache(value))
        return value

    async def _safe(self, operation: Awaitable[None]) -> None:
        try:
            await operation
        except RedisError:
            self._log.warning("cache write failed; ignoring", exc_info=True)
