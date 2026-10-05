"""Redis cache layer for high-performance read operations.

This module provides a Redis-based caching layer to reduce database load
and improve response times for frequently accessed data like user lists
and channel configurations.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from redis.exceptions import WatchError
from decouple import config

LOGGER = logging.getLogger(__name__)


def _reset_marker():
    return Path(config("BACKUP_DIR", default="backup")) / "cache-reset-required"

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
            self.redis = aioredis.from_url(
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
            marker = _reset_marker()
            if marker.exists():
                if not await self.clear_all():
                    raise RuntimeError("Redis namespace needs resetting after database changes")
                marker.unlink(missing_ok=True)
            LOGGER.info(f"Redis cache connected: {REDIS_HOST}:{REDIS_PORT}")
            return True
        except Exception as e:
            LOGGER.warning(f"Redis connection failed: {e}. Running without cache.")
            await self.close()
            self.enabled = False
            return False

    async def close(self) -> None:
        """Close Redis connection gracefully."""
        if self.redis:
            await self.redis.aclose()
            self.redis = None
            LOGGER.info("Redis cache connection closed")

    async def invalidate_user_detail(self, user_id: int) -> bool:
        if not self.enabled or not self.redis:
            return False
        try:
            await self.redis.delete(f"{CACHE_KEY_USER_PREFIX}{user_id}")
            return True
        except Exception as error:
            LOGGER.warning("Cache user invalidation failed: %s", error)
            self.require_reset()
            return False

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
        if not self.enabled or not self.redis:
            return False
        try:
            async with self.redis.pipeline(transaction=True) as pipeline:
                while True:
                    try:
                        await pipeline.watch(CACHE_KEY_USERS)
                        data = await pipeline.get(CACHE_KEY_USERS)
                        if data is None:
                            return False
                        users = json.loads(data)
                        if user_id in users:
                            return True
                        users.append(user_id)
                        pipeline.multi()
                        pipeline.set(CACHE_KEY_USERS, json.dumps(users))
                        await pipeline.execute()
                        return True
                    except WatchError:
                        continue
        except Exception as error:
            LOGGER.warning("Cache add_user_to_list failed: %s", error)
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
            data, version = await self.redis.mget(key, "cutly:version:user")
            if data:
                detail = json.loads(data)
                if detail.pop("_cache_version", "0") == (version or "0"):
                    return detail
        except Exception as e:
            LOGGER.warning(f"Cache get_user_detail failed: {e}")
        return None

    async def set_user_detail(
        self,
        user_id: int,
        user_data: Dict[str, Any],
        version: str | None = None,
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
            version = await self.version("user") if version is None else version
            if version is None:
                return False
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch("cutly:version:user", key)
                if (await pipe.get("cutly:version:user") or "0") != version:
                    return False
                existing = await pipe.get(key)
                data = dict(user_data)
                if existing:
                    activity = json.loads(existing).get("last_activity_at")
                    if activity and (not data.get("last_activity_at") or datetime.fromisoformat(activity) > datetime.fromisoformat(data["last_activity_at"])):
                        data["last_activity_at"] = activity
                pipe.multi()
                pipe.set(key, json.dumps({**data, "_cache_version": version}))
                await pipe.execute()
            return True
        except WatchError:
            return False
        except Exception as e:
            LOGGER.warning(f"Cache set_user_detail failed: {e}")
            self.require_reset()
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
            self.require_reset()
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
            data, version = await self.redis.mget(CACHE_KEY_CHANNELS, "cutly:version:channels")
            if data:
                channels = json.loads(data)
                if channels.pop("_cache_version", "0") != (version or "0"):
                    return None
                LOGGER.debug(f"📥 Channel list retrieved from Redis cache ({len(channels)} channels)")
                return channels
            else:
                LOGGER.debug("📥 Channel list cache miss (no data in Redis)")
        except Exception as e:
            LOGGER.warning(f"❌ Cache get_channel_list failed: {e}")
        return None

    async def set_channel_list(
        self,
        channels: Dict[str, Dict[str, str]],
        version: str | None = None,
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
            version = await self.version("channels") if version is None else version
            if version is None:
                return False
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch("cutly:version:channels")
                if (await pipe.get("cutly:version:channels") or "0") != version:
                    return False
                pipe.multi()
                pipe.set(CACHE_KEY_CHANNELS, json.dumps({**channels, "_cache_version": version}))
                await pipe.execute()
            LOGGER.debug(f"📤 Channel list cached in Redis ({len(channels)} channels)")
            return True
        except WatchError:
            return False
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
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incr("cutly:version:channels")
                pipe.delete(CACHE_KEY_CHANNELS)
                _, deleted_count = await pipe.execute()
            if deleted_count > 0:
                LOGGER.info("🗑️ Channel cache invalidated (Redis key deleted)")
            else:
                LOGGER.debug("🗑️ Channel cache invalidation called but key didn't exist")
            return True
        except Exception as e:
            LOGGER.warning(f"❌ Cache invalidate_channel_cache failed: {e}")
            self.require_reset()
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
            batch = []
            async for key in self.redis.scan_iter(match="cutly:*", count=500):
                batch.append(key)
                if len(batch) >= 500:
                    await self.redis.unlink(*batch)
                    batch.clear()
            if batch:
                await self.redis.unlink(*batch)
            LOGGER.info("All cache cleared")
            return True
        except Exception as e:
            LOGGER.warning(f"Cache clear_all failed: {e}")
            return False

    async def version(self, scope: str) -> str | None:
        if not self.enabled or not self.redis:
            return None
        try:
            return await self.redis.get(f"cutly:version:{scope}") or "0"
        except Exception:
            return None

    async def invalidate_scope(self, scope: str) -> None:
        if not self.enabled or not self.redis:
            return
        try:
            await self.redis.incr(f"cutly:version:{scope}")
        except Exception:
            # Never serve stale protected metadata after a failed invalidation.
            self.require_reset()
            LOGGER.exception("Cache invalidation failed; bypassing Redis")

    def require_reset(self):
        self.enabled = False
        marker = _reset_marker()
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        except OSError:
            LOGGER.exception("Cache bypassed; reset marker could not be saved")

    async def reset_after_restore(self):
        # Persist before attempting Redis so a restart cannot revive stale keys.
        marker = _reset_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        if self.enabled and await self.clear_all():
            # In-flight Telegram predicates can finish a read outside a handler.
            # Never let their pre-restore version match the new empty namespace.
            generation = str(time.time_ns())
            await self.redis.mset({f"cutly:version:{scope}": generation for scope in ("user", "channels", "settings")})
            marker.unlink(missing_ok=True)
        else:
            self.enabled = False

    def begin_restore(self):
        marker = _reset_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

    async def get_snapshot(self, scope: str, identity: str):
        if not self.enabled or not self.redis:
            return None, None
        try:
            version, raw = await self.redis.mget(f"cutly:version:{scope}", f"cutly:object:{scope}:{identity}")
            version = version or "0"
            if raw:
                envelope = json.loads(raw)
                if envelope["version"] == version:
                    return envelope["data"], version
        except Exception:
            return None, None
        return None, version

    async def set_snapshot(self, scope: str, identity: str, data, version):
        if version is None or not self.enabled or not self.redis:
            return
        try:
            version_key = f"cutly:version:{scope}"
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch(version_key)
                if (await pipe.get(version_key) or "0") != version:
                    return
                pipe.multi()
                pipe.set(
                    f"cutly:object:{scope}:{identity}",
                    json.dumps({"version": version, "data": data}), ex=300,
                )
                await pipe.execute()
        except WatchError:
            pass
        except Exception:
            LOGGER.debug("Cache snapshot write failed", exc_info=True)

    async def update_user_activity(self, user_id: int, timestamp: str) -> None:
        if not self.enabled or not self.redis:
            return
        key = f"{CACHE_KEY_USER_PREFIX}{user_id}"
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                while True:
                    try:
                        await pipe.watch(key)
                        raw = await pipe.get(key)
                        if not raw:
                            return
                        data = json.loads(raw)
                        previous = data.get("last_activity_at")
                        if previous and datetime.fromisoformat(previous) >= datetime.fromisoformat(timestamp):
                            return
                        data["last_activity_at"] = timestamp
                        pipe.multi()
                        pipe.set(key, json.dumps(data))
                        await pipe.execute()
                        return
                    except WatchError:
                        continue
        except Exception:
            await self.invalidate_user_detail(user_id)


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

