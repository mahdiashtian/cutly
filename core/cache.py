"""Redis cache layer for high-performance read operations.

This module provides a Redis-based caching layer to reduce database load
and improve response times for frequently accessed data like user lists
and channel configurations.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from decouple import config

LOGGER = logging.getLogger(__name__)

# Redis Configuration
REDIS_HOST = config("REDIS_HOST", default="localhost")
REDIS_PORT = int(config("REDIS_PORT", default="6379"))
REDIS_DB = int(config("REDIS_DB", default="0"))
REDIS_PASSWORD = config("REDIS_PASSWORD", default=None)
REDIS_ENABLED = config("REDIS_ENABLED", default="true").lower() == "true"

# Cache Keys
CACHE_KEY_USERS = "cutly:users:all"
CACHE_KEY_USER_PREFIX = "cutly:user:"
CACHE_KEY_CHANNELS = "cutly:channels:all"
CACHE_KEY_CHANNEL_PREFIX = "cutly:channel:"
CACHE_KEY_ADMIN_USERS = "cutly:users:admins"

# NOTE: No TTL used for persistent cache
# Data is cached permanently and only updated when actual changes occur
# This ensures zero database queries for read operations


class RedisCache:
    """Redis cache manager with async operations.
    
    Provides high-performance caching for user lists, channel configurations,
    and other frequently accessed data.
    
    Examples:
        >>> cache = RedisCache()
        >>> await cache.connect()
        >>> await cache.set_user_list([123, 456, 789])
        >>> users = await cache.get_user_list()
    """
    
    def __init__(self) -> None:
        """Initialize Redis cache manager."""
        self.redis: Optional[aioredis.Redis] = None
        self.enabled = REDIS_ENABLED
        
    async def connect(self) -> bool:
        """Establish Redis connection.
        
        Returns:
            True if connection successful, False otherwise.
        """
        if not self.enabled:
            LOGGER.info("Redis cache is disabled")
            return False
            
        try:
            self.redis = await aioredis.from_url(
                f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
                password=REDIS_PASSWORD,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
            # Test connection
            await self.redis.ping()
            LOGGER.info(f"Redis cache connected: {REDIS_HOST}:{REDIS_PORT}")
            return True
        except Exception as e:
            LOGGER.warning(f"Redis connection failed: {e}. Running without cache.")
            self.enabled = False
            return False
    
    async def close(self) -> None:
        """Close Redis connection gracefully."""
        if self.redis:
            await self.redis.close()
            LOGGER.info("Redis cache connection closed")
    
    async def ping(self) -> bool:
        """Check if Redis is responsive.
        
        Returns:
            True if Redis responds, False otherwise.
        """
        if not self.enabled or not self.redis:
            return False
        try:
            return await self.redis.ping()
        except Exception:
            return False
    
    # User Caching Methods
    
    async def get_user_list(self) -> Optional[List[int]]:
        """Get cached list of all user IDs.
        
        Returns:
            List of user IDs or None if not cached.
        """
        if not self.enabled or not self.redis:
            return None
        try:
            data = await self.redis.get(CACHE_KEY_USERS)
            if data:
                return json.loads(data)
        except Exception as e:
            LOGGER.warning(f"Cache get_user_list failed: {e}")
        return None
    
    async def set_user_list(self, user_ids: List[int]) -> bool:
        """Cache list of all user IDs permanently.
        
        Data is stored without expiration and only updated when users are added.
        
        Args:
            user_ids: List of Telegram user IDs.
            
        Returns:
            True if cached successfully.
        """
        if not self.enabled or not self.redis:
            return False
        try:
            await self.redis.set(
                CACHE_KEY_USERS,
                json.dumps(user_ids)
            )
            return True
        except Exception as e:
            LOGGER.warning(f"Cache set_user_list failed: {e}")
            return False
    
    async def add_user_to_list(self, user_id: int) -> bool:
        """Add a new user ID to cached list.
        
        Args:
            user_id: Telegram user ID to add.
            
        Returns:
            True if added successfully.
        """
        users = await self.get_user_list()
        if users is not None and user_id not in users:
            users.append(user_id)
            return await self.set_user_list(users)
        return False
    
    async def get_user_detail(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get cached user details.
        
        Args:
            user_id: Telegram user ID.
            
        Returns:
            User data dict or None.
        """
        if not self.enabled or not self.redis:
            return None
        try:
            key = f"{CACHE_KEY_USER_PREFIX}{user_id}"
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            LOGGER.warning(f"Cache get_user_detail failed: {e}")
        return None
    
    async def set_user_detail(
        self,
        user_id: int,
        user_data: Dict[str, Any]
    ) -> bool:
        """Cache user details permanently.
        
        Data is stored without expiration and only updated when user data changes.
        
        Args:
            user_id: Telegram user ID.
            user_data: User data dictionary.
            
        Returns:
            True if cached successfully.
        """
        if not self.enabled or not self.redis:
            return False
        try:
            key = f"{CACHE_KEY_USER_PREFIX}{user_id}"
            await self.redis.set(key, json.dumps(user_data))
            return True
        except Exception as e:
            LOGGER.warning(f"Cache set_user_detail failed: {e}")
            return False
    
    async def get_admin_list(self) -> Optional[List[int]]:
        """Get cached list of admin user IDs.
        
        Returns:
            List of admin user IDs or None.
        """
        if not self.enabled or not self.redis:
            return None
        try:
            data = await self.redis.get(CACHE_KEY_ADMIN_USERS)
            if data:
                return json.loads(data)
        except Exception as e:
            LOGGER.warning(f"Cache get_admin_list failed: {e}")
        return None
    
    async def set_admin_list(self, admin_ids: List[int]) -> bool:
        """Cache list of admin user IDs permanently.
        
        Data is stored without expiration and only updated when admin status changes.
        
        Args:
            admin_ids: List of admin Telegram user IDs.
            
        Returns:
            True if cached successfully.
        """
        if not self.enabled or not self.redis:
            return False
        try:
            await self.redis.set(
                CACHE_KEY_ADMIN_USERS,
                json.dumps(admin_ids)
            )
            return True
        except Exception as e:
            LOGGER.warning(f"Cache set_admin_list failed: {e}")
            return False
    
    # Channel Caching Methods
    
    async def get_channel_list(self) -> Optional[Dict[str, Dict[str, str]]]:
        """Get cached channel list.
        
        Returns:
            Dict of channel_id -> {title, link} or None.
        """
        if not self.enabled or not self.redis:
            return None
        try:
            data = await self.redis.get(CACHE_KEY_CHANNELS)
            if data:
                channels = json.loads(data)
                LOGGER.debug(f"📥 Channel list retrieved from Redis cache ({len(channels)} channels)")
                return channels
            else:
                LOGGER.debug("📥 Channel list cache miss (no data in Redis)")
        except Exception as e:
            LOGGER.warning(f"❌ Cache get_channel_list failed: {e}")
        return None
    
    async def set_channel_list(
        self,
        channels: Dict[str, Dict[str, str]]
    ) -> bool:
        """Cache channel list permanently.
        
        Data is stored without expiration and only updated when channels are added/removed.
        
        Args:
            channels: Dict of channel_id -> {title, link}.
            
        Returns:
            True if cached successfully.
        """
        if not self.enabled or not self.redis:
            return False
        try:
            await self.redis.set(
                CACHE_KEY_CHANNELS,
                json.dumps(channels)
            )
            LOGGER.debug(f"📤 Channel list cached in Redis ({len(channels)} channels)")
            return True
        except Exception as e:
            LOGGER.warning(f"❌ Cache set_channel_list failed: {e}")
            return False
    
    async def invalidate_channel_cache(self) -> bool:
        """Invalidate (delete) channel cache to force refresh.
        
        Returns:
            True if invalidated successfully.
        """
        if not self.enabled or not self.redis:
            return False
        try:
            deleted_count = await self.redis.delete(CACHE_KEY_CHANNELS)
            if deleted_count > 0:
                LOGGER.info("🗑️ Channel cache invalidated (Redis key deleted)")
            else:
                LOGGER.debug("🗑️ Channel cache invalidation called but key didn't exist")
            return True
        except Exception as e:
            LOGGER.warning(f"❌ Cache invalidate_channel_cache failed: {e}")
            return False
    
    # Utility Methods
    
    async def clear_all(self) -> bool:
        """Clear all cache keys (use with caution).
        
        Returns:
            True if cleared successfully.
        """
        if not self.enabled or not self.redis:
            return False
        try:
            # Delete all keys matching our pattern
            keys = await self.redis.keys("cutly:*")
            if keys:
                await self.redis.delete(*keys)
            LOGGER.info("All cache cleared")
            return True
        except Exception as e:
            LOGGER.warning(f"Cache clear_all failed: {e}")
            return False


# Global cache instance
_cache_instance: Optional[RedisCache] = None


def get_cache() -> RedisCache:
    """Get or create global cache instance.
    
    Returns:
        Global RedisCache instance.
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = RedisCache()
    return _cache_instance

