import asyncio
from unittest.mock import AsyncMock, Mock
import pytest
from core.cache import CACHE_KEY_USERS, RedisCache
from services import create_user_from_db, userid_list
from services import user as user_service


async def test_cache_hits_avoid_database(isolated_db, monkeypatch):
    await isolated_db.set_user_list([1, 2])
    fail = AsyncMock(side_effect=AssertionError("DB should not be queried"))
    monkeypatch.setattr(user_service._repo, "get_userids_list", fail)
    assert await userid_list() == [1, 2]
    assert await isolated_db.redis.ttl(CACHE_KEY_USERS) == -1


async def test_concurrent_cached_additions_keep_all_users(isolated_db):
    await isolated_db.set_user_list([])
    await asyncio.gather(*(isolated_db.add_user_to_list(i) for i in range(40)))
    assert sorted(await isolated_db.get_user_list()) == list(range(40))


async def test_corrupt_cache_falls_back_to_db(isolated_db):
    await create_user_from_db({"userid": 42})
    await isolated_db.redis.set(CACHE_KEY_USERS, "invalid json")
    assert await userid_list() == [42]


async def test_disabled_or_failed_cache_returns_misses(isolated_db):
    isolated_db.enabled = False
    assert await isolated_db.get_user_list() is None
    assert not await isolated_db.set_user_list([1])
    isolated_db.enabled = True
    isolated_db.redis.pipeline = Mock(side_effect=OSError("redis unavailable"))
    assert await isolated_db.get_user_list() is None
    assert await userid_list() == []


async def test_connect_and_shutdown_use_async_redis_client(monkeypatch):
    from core import cache as module

    fake = AsyncMock()
    monkeypatch.setattr(module.aioredis.Redis, "from_pool", lambda *args, **kwargs: fake)
    cache = RedisCache()
    cache.enabled = True
    assert await cache.connect()
    await cache.close()
    fake.aclose.assert_awaited_once()
    assert cache.redis is None
