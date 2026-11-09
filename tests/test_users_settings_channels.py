from __future__ import annotations

import asyncio

from redis.exceptions import ConnectionError as RedisConnectionError

from repositories.redis import keys


async def test_ensure_creates_once_even_concurrently(container):
    users = await asyncio.gather(*(container.users.ensure(5, access_hash=77) for _ in range(10)))
    assert {user.id for user in users} == {5}
    assert (await container.users.get(5)).access_hash == 77


async def test_activity_is_written_once_per_window(container):
    await container.users.ensure(5)
    first = (await container.users.profile(5)).last_active_at
    await container.users.ensure(5)
    assert (await container.users.profile(5)).last_active_at == first
    await container.state_redis.delete(keys.activity_touch(5))
    await container.users.ensure(5)
    assert (await container.users.profile(5)).last_active_at >= first


async def test_admin_rules(container):
    assert await container.users.is_admin(1)  # ADMIN_MASTER, not stored in the DB
    assert not await container.users.set_admin(42, True)  # unknown users cannot be promoted
    await container.users.ensure(42)
    assert await container.users.set_admin(42, True)
    assert await container.users.is_admin(42)
    assert await container.users.admin_ids() == [42]


async def test_cache_outage_falls_back_to_database(container, monkeypatch):
    await container.users.ensure(7)

    async def broken(*_args, **_kwargs):
        raise RedisConnectionError("down")

    monkeypatch.setattr(container.cache_redis, "get", broken)
    assert (await container.users.get(7)).id == 7


async def test_settings_singleton(container):
    assert (await container.settings_service.get()).show_file_captions
    await container.settings_service.set_global_caption("G")
    toggled = await container.settings_service.toggle_file_captions()
    assert toggled.global_caption == "G" and not toggled.show_file_captions
    assert toggled.caption_for("own") == "G"
    assert (await container.settings_service.get()) == toggled


async def test_channels_cache_and_fingerprint(container):
    channels = container.channels
    assert await channels.add(chat_ref="news", invite_link="https://t.me/news", title="News")
    assert not await channels.add(chat_ref="news", invite_link="https://t.me/news", title="News")
    first = channels.fingerprint(await channels.list())
    await channels.add(chat_ref="-1001", invite_link="https://t.me/+x", title="Private")
    listed = await channels.list()
    assert [c.chat_ref for c in listed] == ["news", "-1001"] and listed[1].peer == -1001
    assert channels.fingerprint(listed) != first
    assert await channels.remove("https://t.me/+x")
    assert [c.chat_ref for c in await channels.list()] == ["news"]
