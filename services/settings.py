from __future__ import annotations

from repositories.postgres.unit_of_work import UnitOfWorkFactory
from repositories.redis.caches import SettingsCache
from schemas.settings import BotSettingsDTO
from services.base import Service


class SettingsService(Service):
    def __init__(self, uow: UnitOfWorkFactory, cache: SettingsCache) -> None:
        super().__init__(uow)
        self._cache = cache

    async def get(self) -> BotSettingsDTO:
        return await self._cached(read_cache=self._cache.get, read_db=self._load,
                                  write_cache=self._cache.set)

    async def refresh_cache(self) -> None:
        await self._safe(self._cache.set(await self._load()))

    async def _load(self) -> BotSettingsDTO:
        async with self._uow() as uow:
            return await uow.settings.get()

    async def set_global_caption(self, caption: str | None) -> BotSettingsDTO:
        return await self._update(global_caption=caption)

    async def toggle_file_captions(self) -> BotSettingsDTO:
        current = await self.get()
        return await self._update(show_file_captions=not current.show_file_captions)

    async def _update(self, **values) -> BotSettingsDTO:
        async with self._uow() as uow:
            settings = await uow.settings.update(**values)
        await self._safe(self._cache.set(settings))
        return settings
