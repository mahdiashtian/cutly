"""Bot-wide configuration singleton service."""

from __future__ import annotations

from typing import Optional

from core.models import BotSettings

_SETTINGS_ID = 1


async def get_bot_settings() -> BotSettings:
    """Return the singleton settings row, creating it on first access."""

    settings, _ = await BotSettings.get_or_create(id=_SETTINGS_ID)
    return settings


async def set_global_caption(caption: Optional[str]) -> BotSettings:
    """Persist the caption shown at the start of every sent file's caption."""

    settings = await get_bot_settings()
    settings.global_caption = caption
    await settings.save(update_fields=["global_caption"])
    return settings


async def set_show_file_captions(enabled: bool) -> BotSettings:
    """Toggle whether each file's own caption is shown alongside the global one."""

    settings = await get_bot_settings()
    settings.show_file_captions = enabled
    await settings.save(update_fields=["show_file_captions"])
    return settings
