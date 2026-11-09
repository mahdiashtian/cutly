"""Composition root: the only place that wires infrastructure into services.

Both the bot and the Celery worker build one ``Container``::

    container = Container(settings)
    await container.startup()
    try:
        ...
    finally:
        await container.shutdown()
"""
from __future__ import annotations

import logging

from redis.asyncio import Redis

from core.config import Settings
from db.engine import Database
from db.redis import RedisClient
from repositories.postgres.unit_of_work import UnitOfWork
from repositories.redis import keys
from repositories.redis.base import delete_matching
from repositories.redis.caches import ChannelCache, LinkCache, SettingsCache, UserCache
from repositories.redis.conversations import ConversationStore
from repositories.redis.markers import ActivityThrottle, JoinedChannelsMarker, MaintenanceFlag, RateLimiter
from repositories.redis.restores import StagedRestoreStore
from repositories.redis.uploads import UploadSessionStore
from services.backup import BackupService
from services.broadcasts import BroadcastService
from services.channels import ChannelService
from services.links import LinkService
from services.restore import RestoreService
from services.settings import SettingsService
from services.stats import StatsService
from services.users import UserService

log = logging.getLogger(__name__)


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database: Database
        self._redis_clients: list[RedisClient] = []
        self._fake_redis: Redis | None = None

    async def startup(self) -> None:
        s = self.settings
        self.database = Database(
            s.db_url, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow,
            pool_timeout=s.db_pool_timeout, pool_recycle=s.db_pool_recycle,
            command_timeout=s.db_command_timeout, echo=s.db_echo,
        )
        cache_redis, state_redis = self._connect_redis()
        self.cache_redis, self.state_redis = cache_redis, state_redis

        def uow() -> UnitOfWork:
            return UnitOfWork(self.database.sessionmaker)

        ttl = s.cache_ttl_seconds
        self.users = UserService(
            uow, UserCache(cache_redis, ttl_seconds=ttl),
            ActivityThrottle(state_redis, window_seconds=s.activity_touch_seconds),
            admin_master=s.admin_master,
        )
        self.links = LinkService(uow, LinkCache(cache_redis, ttl_seconds=ttl))
        self.channels = ChannelService(uow, ChannelCache(cache_redis, ttl_seconds=ttl))
        self.settings_service = SettingsService(uow, SettingsCache(cache_redis, ttl_seconds=ttl))
        self.broadcasts = BroadcastService(uow)
        self.stats = StatsService(uow)
        self.backups = BackupService(self.database, s.backup_dir, pg_dump_path=s.pg_dump_path,
                                     pg_tool_timeout=s.pg_tool_timeout)
        self.restores = RestoreService(self.database, s.backup_dir, max_bytes=s.restore_max_bytes)

        # Cross-process state (state Redis: must never be evicted).
        self.conversations = ConversationStore(state_redis, ttl_seconds=s.conversation_ttl_seconds)
        self.uploads = UploadSessionStore(state_redis, ttl_seconds=s.conversation_ttl_seconds)
        self.staged_restores = StagedRestoreStore(state_redis)
        self.maintenance = MaintenanceFlag(state_redis)
        self.joined_marker = JoinedChannelsMarker(cache_redis, ttl_seconds=s.forced_join_cache_seconds)
        # Abuse protection lives on the state Redis: an evicted counter would reset a limit.
        self.flood_limiter = RateLimiter(state_redis, name="updates", limit=s.user_rate_limit,
                                         window_seconds=s.user_rate_window_seconds)
        self.password_limiter = RateLimiter(state_redis, name="password", limit=s.password_attempts,
                                            window_seconds=s.password_window_seconds)

    def _connect_redis(self) -> tuple[Redis, Redis]:
        if self.settings.environment == "test":
            import fakeredis

            self._fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
            return self._fake_redis, self._fake_redis
        cache = RedisClient(self.settings.redis_cache_url, max_connections=self.settings.redis_max_connections)
        self._redis_clients.append(cache)
        if self.settings.redis_state_url == self.settings.redis_cache_url:
            return cache.client, cache.client
        state = RedisClient(self.settings.redis_state_url, max_connections=self.settings.redis_max_connections)
        self._redis_clients.append(state)
        return cache.client, state.client

    async def warm_cache(self) -> None:
        """Preload the small, configuration-sized data read on every command.

        Per-user and per-link entries are *not* preloaded: they fill on first
        read, so memory follows real traffic instead of table sizes.
        """
        try:
            await self.channels.refresh_cache()
            await self.settings_service.refresh_cache()
        except Exception:  # noqa: BLE001 - cache-aside still works without warmup
            log.exception("cache warmup failed")

    async def reset_after_restore(self) -> None:
        """Drop everything derived from the replaced data."""
        for redis, pattern in (
            (self.cache_redis, keys.cache_pattern()),
            (self.state_redis, keys.conversation_pattern()),
            (self.state_redis, keys.upload_session_pattern()),
        ):
            await delete_matching(redis, pattern)
        await self.warm_cache()

    async def shutdown(self) -> None:
        for client in self._redis_clients:
            await client.close()
        self._redis_clients.clear()
        if self._fake_redis is not None:
            await self._fake_redis.aclose()
            self._fake_redis = None
        await self.database.dispose()
