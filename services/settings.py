"""Singleton bot settings persisted with SQLAlchemy."""

from sqlalchemy.exc import IntegrityError
from core.database import session_scope
from core.models import BotSettings
from core.cache import get_cache
from core.maintenance import database_operation


@database_operation
async def get_bot_settings() -> BotSettings:
    cache = get_cache()
    data, version = await cache.get_snapshot("settings", "1")
    if data is not None:
        return BotSettings(**data)
    async with cache.fill_lock("settings"):
        data, version = await cache.get_snapshot("settings", "1")
        if data is not None:
            return BotSettings(**data)
        settings = await _load_settings()
        await cache.set_snapshot(
            "settings",
            "1",
            {
                "id": settings.id,
                "global_caption": settings.global_caption,
                "show_file_captions": settings.show_file_captions,
            },
            version,
        )
        return settings


async def _load_settings():
    async with session_scope() as session:
        settings = await session.get(BotSettings, 1)
        if settings is not None:
            return settings
    try:
        async with session_scope() as session:
            settings = BotSettings(id=1)
            session.add(settings)
            await session.flush()
        return settings
    except IntegrityError:
        async with session_scope() as session:
            settings = await session.get(BotSettings, 1)
            if settings is None:
                raise
            return settings


@database_operation
async def _update(**values) -> BotSettings:
    await get_bot_settings()
    async with session_scope() as session:
        settings = await session.get(BotSettings, 1)
        for key, value in values.items():
            setattr(settings, key, value)
        await session.flush()
    await get_cache().invalidate_scope("settings")
    return settings


async def set_global_caption(caption: str | None) -> BotSettings:
    return await _update(global_caption=caption)


async def set_show_file_captions(enabled: bool) -> BotSettings:
    return await _update(show_file_captions=enabled)
