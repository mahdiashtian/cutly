"""Bounded Redis metadata caches; SQL remains the source of truth."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime

import redis.asyncio as aioredis
from redis.exceptions import WatchError
from decouple import config
from core.concurrency import KeyedLocks
from core.maintenance import database_operation

LOGGER = logging.getLogger(__name__)
REDIS_HOST = config("REDIS_HOST", default="localhost")
REDIS_PORT = config("REDIS_PORT", default=6379, cast=int)
REDIS_DB = config("REDIS_DB", default=0, cast=int)
REDIS_PASSWORD = config("REDIS_PASSWORD", default=None)
REDIS_ENABLED = config("REDIS_ENABLED", default="true").lower() == "true"

CACHE_KEY_USERS = "cutly:users:all"
CACHE_KEY_USER_MEMBERS = "cutly:users:members"
CACHE_KEY_USER_PREFIX = "cutly:user:"
CACHE_KEY_CHANNELS = "cutly:channels:all"
CACHE_KEY_CHANNEL_PREFIX = "cutly:channel:"
CACHE_KEY_ADMIN_USERS = "cutly:users:admins"
CACHE_TTL, USER_TTL, VERSION_TTL = 300, 600, 1200
_UNSET = object()


def _reset_marker():
    return Path(config("BACKUP_DIR", default="backup")) / "cache-reset-required"


def _version_ttl(scope):
    return VERSION_TTL if scope.startswith(("file:", "album:", "user:")) else None


class RedisCache:
    def __init__(self):
        self.redis = None
        self.enabled = REDIS_ENABLED
        self._requested_enabled = REDIS_ENABLED
        self._fills = KeyedLocks()

    async def connect(self):
        if not self.enabled:
            return False
        # Do not expose the old namespace while checking its reset marker.
        self.enabled = False
        try:
            pool = aioredis.BlockingConnectionPool.from_url(
                f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
                password=REDIS_PASSWORD or None,
                decode_responses=True,
                encoding="utf-8",
                max_connections=config("REDIS_MAX_CONNECTIONS", default=64, cast=int),
                timeout=config("REDIS_POOL_TIMEOUT", default=5, cast=float),
                socket_timeout=config("REDIS_SOCKET_TIMEOUT", default=2, cast=float),
                socket_connect_timeout=2,
                socket_keepalive=True,
            )
            self.redis = aioredis.Redis.from_pool(pool)
            await self.redis.ping()
            marker = _reset_marker()
            if marker.exists():
                if not await self._clear_namespace():
                    raise RuntimeError("Redis namespace needs resetting")
                marker.unlink(missing_ok=True)
            self.enabled = True
            return True
        except Exception:
            LOGGER.warning("Redis unavailable; using SQL", exc_info=True)
            try:
                await self.close()
            except Exception:
                LOGGER.debug("Failed to close unavailable Redis client", exc_info=True)
            return False

    @database_operation
    async def recover(self):
        """Reconnect only when Redis was configured; reset before serving reads."""
        async with self._fills.hold(["redis-recovery"]):
            if self.enabled or not self._requested_enabled:
                return self.enabled
            try:
                await self.close()
            except Exception:
                LOGGER.debug("Redis reconnect cleanup failed", exc_info=True)
            self.enabled = True
            return await self.connect()

    async def close(self):
        if self.redis is not None:
            client, self.redis = self.redis, None
            await client.aclose()

    async def ping(self):
        if self.enabled and self.redis is not None:
            try:
                return await self.redis.ping()
            except Exception:
                pass
        return False

    @asynccontextmanager
    async def fill_lock(self, scope):
        """Coalesce cold reads without retaining a lock per historic key."""
        async with self._fills.hold([scope]):
            yield

    async def version(self, scope):
        if not self.enabled or self.redis is None:
            return None
        key = f"cutly:version:{scope}"
        try:
            value = await self.redis.get(key)
            if value is None:
                await self.redis.set(
                    key, uuid.uuid4().hex, nx=True, ex=_version_ttl(scope)
                )
                value = await self.redis.get(key)
            return value
        except Exception:
            return None

    async def invalidate_scope(self, scope):
        if not self.enabled or self.redis is None:
            return
        try:
            await self.redis.set(
                f"cutly:version:{scope}", uuid.uuid4().hex, ex=_version_ttl(scope)
            )
        except asyncio.CancelledError:
            self.require_reset()
            raise
        except Exception:
            self.require_reset()
            LOGGER.warning("Cache invalidation failed; bypassing Redis", exc_info=True)

    async def invalidate_scopes(self, scopes):
        if not self.enabled or self.redis is None:
            return
        scopes = sorted(set(scopes))
        try:
            for start in range(0, len(scopes), 500):
                async with self.redis.pipeline(transaction=False) as pipe:
                    for scope in scopes[start : start + 500]:
                        pipe.set(
                            f"cutly:version:{scope}",
                            uuid.uuid4().hex,
                            ex=_version_ttl(scope),
                        )
                    await pipe.execute()
        except asyncio.CancelledError:
            self.require_reset()
            raise
        except Exception:
            self.require_reset()

    async def get_user_list(self):
        if not self.enabled or self.redis is None:
            return None
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.get(CACHE_KEY_USERS)
                pipe.zrange(CACHE_KEY_USER_MEMBERS, 0, -1)
                marker, members = await pipe.execute()
            if marker == "v2":
                if "__empty__" not in members:
                    return None  # The index was evicted separately from its marker.
                return [int(value) for value in members if value != "__empty__"]
            if marker:
                legacy = json.loads(marker)
                if isinstance(legacy, list):
                    return [int(value) for value in legacy]
        except Exception:
            LOGGER.debug("User index read failed", exc_info=True)
        return None

    async def set_user_list(self, user_ids, version=_UNSET):
        if not self.enabled or self.redis is None:
            return False
        version = await self.version("users") if version is _UNSET else version
        if version is None:
            return False
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch("cutly:version:users")
                if await pipe.get("cutly:version:users") != version:
                    return False
                pipe.multi()
                pipe.zadd(CACHE_KEY_USER_MEMBERS, {"__empty__": 0}, nx=True)
                # Merge additions committed during the SQL snapshot; never replace.
                for start in range(0, len(user_ids), 500):
                    members = {
                        str(value): index + 1
                        for index, value in enumerate(
                            user_ids[start : start + 500], start
                        )
                    }
                    pipe.zadd(CACHE_KEY_USER_MEMBERS, members, nx=True)
                pipe.set(CACHE_KEY_USERS, "v2")
                await pipe.execute()
            return True
        except WatchError:
            return False
        except Exception:
            self.require_reset()
            return False

    async def add_user_to_list(self, user_id, *, rank=None):
        if not self.enabled or self.redis is None:
            return False
        try:
            marker = await self.redis.get(CACHE_KEY_USERS)
            if marker and marker != "v2":
                try:
                    await self.set_user_list(json.loads(marker))
                except (ValueError, TypeError):
                    await self.redis.delete(CACHE_KEY_USERS)
            # An atomic insertion, including before the full list is hydrated.
            await self.redis.zadd(
                CACHE_KEY_USER_MEMBERS,
                {str(user_id): rank if rank is not None else user_id},
                nx=True,
            )
            return True
        except asyncio.CancelledError:
            self.require_reset()
            raise
        except Exception:
            self.require_reset()
            return False

    async def invalidate_user_index(self):
        await self.invalidate_scope("users")
        if self.enabled and self.redis is not None:
            try:
                await self.redis.delete(CACHE_KEY_USERS, CACHE_KEY_USER_MEMBERS)
            except asyncio.CancelledError:
                self.require_reset()
                raise
            except Exception:
                self.require_reset()

    async def user_version(self, user_id):
        global_version = await self.version("user")
        local_version = await self.version(f"user:{user_id}")
        return (
            (global_version, local_version)
            if global_version and local_version
            else None
        )

    async def invalidate_user_detail(self, user_id):
        await self.invalidate_scope(f"user:{user_id}")
        if not self.enabled or self.redis is None:
            return False
        try:
            await self.redis.delete(f"{CACHE_KEY_USER_PREFIX}{user_id}")
            return True
        except Exception:
            self.require_reset()
            return False

    async def get_user_detail(self, user_id):
        if not self.enabled or self.redis is None:
            return None
        try:
            raw, global_version, local_version = await self.redis.mget(
                f"{CACHE_KEY_USER_PREFIX}{user_id}",
                "cutly:version:user",
                f"cutly:version:user:{user_id}",
            )
            if raw:
                data = json.loads(raw)
                if (
                    data.pop("_cache_version", None) == global_version
                    and data.pop("_user_version", None) == local_version
                    and local_version
                ):
                    return data
        except Exception:
            LOGGER.debug("User profile read failed", exc_info=True)
        return None

    async def set_user_detail(self, user_id, user_data, version=_UNSET):
        if not self.enabled or self.redis is None:
            return False
        version = await self.user_version(user_id) if version is _UNSET else version
        if version is None:
            return False
        key = f"{CACHE_KEY_USER_PREFIX}{user_id}"
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch(
                    "cutly:version:user", f"cutly:version:user:{user_id}", key
                )
                if (
                    tuple(
                        await pipe.mget(
                            "cutly:version:user", f"cutly:version:user:{user_id}"
                        )
                    )
                    != version
                ):
                    return False
                raw = await pipe.get(key)
                data = dict(user_data)
                if raw:
                    activity = json.loads(raw).get("last_activity_at")
                    if activity and (
                        not data.get("last_activity_at")
                        or datetime.fromisoformat(activity)
                        > datetime.fromisoformat(data["last_activity_at"])
                    ):
                        data["last_activity_at"] = activity
                pipe.multi()
                pipe.set(
                    key,
                    json.dumps(
                        {
                            **data,
                            "_cache_version": version[0],
                            "_user_version": version[1],
                        }
                    ),
                    ex=USER_TTL,
                )
                await pipe.execute()
            return True
        except WatchError:
            return False
        except Exception:
            LOGGER.debug("User profile write failed", exc_info=True)
            return False

    async def get_admin_list(self):
        return (await self.get_snapshot("admins", "ids"))[0]

    async def set_admin_list(self, admin_ids, version=_UNSET):
        version = await self.version("admins") if version is _UNSET else version
        return await self.set_snapshot("admins", "ids", admin_ids, version)

    async def get_channel_list(self):
        if not self.enabled or self.redis is None:
            return None
        try:
            raw, version = await self.redis.mget(
                CACHE_KEY_CHANNELS, "cutly:version:channels"
            )
            if raw:
                channels = json.loads(raw)
                if channels.pop("_cache_version", None) == version and version:
                    return channels
        except Exception:
            LOGGER.debug("Channel read failed", exc_info=True)
        return None

    async def set_channel_list(self, channels, version=_UNSET):
        version = await self.version("channels") if version is _UNSET else version
        return await self._set_snapshot(
            "channels",
            CACHE_KEY_CHANNELS,
            {**channels, "_cache_version": version},
            version,
        )

    async def invalidate_channel_cache(self):
        await self.invalidate_scope("channels")
        if self.enabled and self.redis is not None:
            try:
                await self.redis.delete(CACHE_KEY_CHANNELS)
                return True
            except Exception:
                self.require_reset()
        return False

    async def get_snapshot(self, scope, identity):
        if not self.enabled or self.redis is None:
            return None, None
        try:
            version, raw = await self.redis.mget(
                f"cutly:version:{scope}", f"cutly:object:{scope}:{identity}"
            )
            if version is None:
                version = await self.version(scope)
            if raw:
                envelope = json.loads(raw)
                if version and envelope["version"] == version:
                    return envelope["data"], version
            return None, version
        except Exception:
            return None, None

    async def _set_snapshot(self, scope, key, data, version):
        if version is None or not self.enabled or self.redis is None:
            return False
        try:
            version_key = f"cutly:version:{scope}"
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch(version_key)
                if await pipe.get(version_key) != version:
                    return False
                pipe.multi()
                pipe.set(key, json.dumps(data), ex=CACHE_TTL)
                await pipe.execute()
            return True
        except WatchError:
            return False
        except Exception:
            LOGGER.debug("Cache fill failed", exc_info=True)
            return False

    async def set_snapshot(self, scope, identity, data, version):
        return await self._set_snapshot(
            scope,
            f"cutly:object:{scope}:{identity}",
            {"version": version, "data": data},
            version,
        )

    async def update_user_activity(self, user_id, timestamp):
        if not self.enabled or self.redis is None:
            return
        key = f"{CACHE_KEY_USER_PREFIX}{user_id}"
        try:
            # Bound contention; a miss is safer than an unbounded WATCH loop.
            for _ in range(3):
                try:
                    async with self.redis.pipeline(transaction=True) as pipe:
                        await pipe.watch(key)
                        raw = await pipe.get(key)
                        if not raw:
                            return
                        data = json.loads(raw)
                        previous = data.get("last_activity_at")
                        if previous and datetime.fromisoformat(
                            previous
                        ) >= datetime.fromisoformat(timestamp):
                            return
                        data["last_activity_at"] = timestamp
                        pipe.multi()
                        pipe.set(key, json.dumps(data), keepttl=True)
                        await pipe.execute()
                        return
                except WatchError:
                    continue
        except Exception:
            LOGGER.debug("Activity cache update failed", exc_info=True)
        await self.invalidate_user_detail(user_id)

    async def clear_all(self):
        if not self.enabled or self.redis is None:
            return False
        return await self._clear_namespace()

    async def _clear_namespace(self):
        try:
            batch = []
            async for key in self.redis.scan_iter(match="cutly:*", count=500):
                batch.append(key)
                if len(batch) >= 500:
                    await self.redis.unlink(*batch)
                    batch.clear()
            if batch:
                await self.redis.unlink(*batch)
            return True
        except Exception:
            LOGGER.warning("Cache reset failed", exc_info=True)
            return False

    def require_reset(self):
        self.enabled = False
        try:
            self.begin_restore()
        except OSError:
            LOGGER.exception("Cache bypassed; reset marker could not be saved")

    def begin_restore(self):
        marker = _reset_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

    async def reset_after_restore(self):
        self.begin_restore()
        if self.enabled and await self.clear_all():
            generation = uuid.uuid4().hex
            await self.redis.mset(
                {
                    f"cutly:version:{scope}": generation
                    for scope in ("user", "channels", "settings", "users", "admins")
                }
            )
            _reset_marker().unlink(missing_ok=True)
        else:
            self.enabled = False


_cache_instance = None


def get_cache():
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = RedisCache()
    return _cache_instance
