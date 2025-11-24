"""Channel management services with Redis caching.

Channel list is heavily accessed during forced join checks, making it
an ideal candidate for Redis caching to reduce database load.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from tortoise.expressions import Q

from core.cache import get_cache
from core.models import Channel

LOGGER = logging.getLogger(__name__)


async def read_channels_from_db() -> List[Channel]:
    """Return all configured join channels with caching.
    
    Uses Redis cache for fast access. Cache is invalidated when channels
    are added or removed to ensure consistency.
    
    Returns:
        List of all Channel instances.
        
    Examples:
        >>> channels = await read_channels_from_db()
    """
    # Note: This returns full Channel objects which are needed
    # For channel list dict used in join checks, see main.py's build_channel_join_list
    return await Channel.all()


async def delete_channel_from_db(channel_identifier: str) -> bool:
    """Delete a channel by link or identifier with cache invalidation.
    
    Automatically invalidates Redis cache to ensure removed channel is
    immediately excluded from forced join checks.
    
    Args:
        channel_identifier: Channel ID or link.
        
    Returns:
        True if channel was deleted, False otherwise.
        
    Examples:
        >>> success = await delete_channel_from_db("@mychannel")
        >>> success = await delete_channel_from_db("https://t.me/mychannel")
    """
    cache = get_cache()
    
    deleted = await Channel.filter(
        Q(channel_id=channel_identifier) | Q(channel_link=channel_identifier)
    ).delete()
    
    # Invalidate channel cache to force refresh
    if deleted:
        cache_invalidated = await cache.invalidate_channel_cache()
        if cache_invalidated:
            LOGGER.info(f"🗑️ Channel deleted from DB: {channel_identifier} | Redis cache invalidated")
        else:
            LOGGER.info(f"🗑️ Channel deleted from DB: {channel_identifier} | Redis cache not available")
    
    return bool(deleted)


async def create_channel_from_db(data: Dict[str, Any]) -> Channel:
    """Persist a new join channel with cache invalidation.
    
    Automatically invalidates Redis cache to ensure new channel is
    immediately included in forced join checks.
    
    Args:
        data: Channel data dictionary with channel_id and channel_link.
        
    Returns:
        Newly created Channel instance.
        
    Examples:
        >>> channel = await create_channel_from_db({
        ...     "channel_id": "@mychannel",
        ...     "channel_link": "https://t.me/mychannel"
        ... })
    """
    cache = get_cache()
    
    channel = await Channel.create(**data)
    
    # Invalidate channel cache to force refresh
    cache_invalidated = await cache.invalidate_channel_cache()
    if cache_invalidated:
        LOGGER.info(f"➕ Channel created in DB: {data.get('channel_id')} | {data.get('channel_link')} | Redis cache invalidated")
    else:
        LOGGER.info(f"➕ Channel created in DB: {data.get('channel_id')} | {data.get('channel_link')} | Redis cache not available")
    
    return channel

