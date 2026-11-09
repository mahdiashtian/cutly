from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError

from repositories.postgres.unit_of_work import UnitOfWorkFactory
from repositories.redis.caches import ChannelCache
from schemas.channel import ChannelDTO
from services.base import Service


class ChannelService(Service):
    """Mandatory-join channels. The list is tiny and read on every user command,
    so it is always served from Redis and rewritten after each change."""

    def __init__(self, uow: UnitOfWorkFactory, cache: ChannelCache) -> None:
        super().__init__(uow)
        self._cache = cache

    async def list(self) -> list[ChannelDTO]:
        return await self._cached(read_cache=self._cache.get, read_db=self._load,
                                  write_cache=self._cache.set)

    async def add(self, *, chat_ref: str, invite_link: str, title: str) -> bool:
        try:
            async with self._uow() as uow:
                await uow.channels.add(chat_ref=chat_ref, invite_link=invite_link, title=title)
        except IntegrityError:
            return False  # already configured
        await self.refresh_cache()
        return True

    async def remove(self, identifier: str) -> bool:
        async with self._uow() as uow:
            removed = await uow.channels.delete(identifier)
        if removed:
            await self.refresh_cache()
        return removed

    async def set_title(self, channel_id: int, title: str) -> None:
        async with self._uow() as uow:
            await uow.channels.set_title(channel_id, title)
        await self.refresh_cache()

    async def _load(self) -> list[ChannelDTO]:
        async with self._uow() as uow:
            return await uow.channels.list_all()

    async def refresh_cache(self) -> None:
        await self._safe(self._cache.set(await self._load()))

    @staticmethod
    def fingerprint(channels: list[ChannelDTO]) -> str:
        """Identifies the current channel set (see JoinedChannelsMarker)."""
        refs = ",".join(sorted(channel.chat_ref for channel in channels))
        return hashlib.sha256(refs.encode()).hexdigest()[:16]
