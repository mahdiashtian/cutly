"""Cache repositories: one small class per cached entity."""
from __future__ import annotations

from pydantic import TypeAdapter

from repositories.redis import keys
from repositories.redis.base import RedisCache
from schemas.channel import ChannelDTO
from schemas.link import LinkDTO
from schemas.settings import BotSettingsDTO
from schemas.user import UserDTO

_CHANNELS = TypeAdapter(list[ChannelDTO])


class UserCache(RedisCache):
    async def get(self, user_id: int) -> UserDTO | None:
        return await self._get_model(keys.user(user_id), UserDTO)

    async def set(self, user: UserDTO) -> None:
        await self._set_model(keys.user(user.id), user)


class LinkCache(RedisCache):
    async def get(self, code: str) -> LinkDTO | None:
        return await self._get_model(keys.link(code), LinkDTO)

    async def set(self, link: LinkDTO) -> None:
        await self._set_model(keys.link(link.code), link)

    async def set_absent(self, code: str) -> None:
        await self._set_model(keys.link(code), None)

    async def invalidate(self, code: str) -> None:
        await self._delete(keys.link(code))


class ChannelCache(RedisCache):
    async def get(self) -> list[ChannelDTO]:
        return await self._get_list(keys.mandatory_channels(), _CHANNELS)

    async def set(self, channels: list[ChannelDTO]) -> None:
        await self._set_list(keys.mandatory_channels(), channels, _CHANNELS)


class SettingsCache(RedisCache):
    async def get(self) -> BotSettingsDTO | None:
        return await self._get_model(keys.settings(), BotSettingsDTO)

    async def set(self, settings: BotSettingsDTO) -> None:
        await self._set_model(keys.settings(), settings)
