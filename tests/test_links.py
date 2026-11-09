from __future__ import annotations

import asyncio
from datetime import timedelta

from core.clock import utcnow
from core.enums import MediaType
from repositories.redis import keys
from tests.conftest import media


async def _link(container, owner=10, **limits):
    await container.users.ensure(owner)
    return await container.links.create(owner, [media(), media(MediaType.VIDEO), media(MediaType.AUDIO)], **{
        "expires_at": None, "max_downloads": None, **limits,
    })


async def test_create_keeps_media_order_and_caches(container):
    link = await _link(container)
    assert [item.position for item in link.media] == [0, 1, 2]
    assert [item.media_type for item in link.media] == [MediaType.PHOTO, MediaType.VIDEO, MediaType.AUDIO]
    assert await container.cache_redis.get(keys.link(link.code)) is not None
    assert (await container.links.get(link.code)) == link


async def test_unknown_code_is_negative_cached(container):
    assert await container.links.get("missing") is None
    assert await container.cache_redis.get(keys.link("missing")) == "\x00absent"


async def test_download_cap_is_exact_under_concurrency(container):
    link = await _link(container, max_downloads=3)
    results = await asyncio.gather(*(container.links.reserve_download(link) for _ in range(20)))
    assert sorted(r for r in results if r is not None) == [1, 2, 3]
    assert results.count(None) == 17


async def test_released_slot_can_be_used_again(container):
    link = await _link(container, max_downloads=1)
    assert await container.links.reserve_download(link) == 1
    assert await container.links.reserve_download(link) is None
    await container.links.release_download(link)
    assert await container.links.reserve_download(link) == 1


async def test_expired_link_cannot_be_reserved(container):
    link = await _link(container, expires_at=utcnow() - timedelta(seconds=1))
    assert link.is_expired
    assert await container.links.reserve_download(link) is None


async def test_password_is_hashed_and_verified(container):
    link = await _link(container)
    await container.links.set_password(link, "s3cret")
    stored = await container.links.get(link.code)
    assert stored.password_hash.startswith("scrypt$") and "s3cret" not in stored.password_hash
    assert await container.links.check_password(stored, "s3cret")
    assert not await container.links.check_password(stored, "wrong")
    await container.links.set_password(stored, None)
    assert (await container.links.get(link.code)).password_hash is None


async def test_caption_change_is_written_through(container):
    link = await _link(container)
    await container.links.set_caption(link, "hello")
    cached = await container.links._cache.get(link.code)  # straight from Redis
    assert cached.caption == "hello"


async def test_delete_is_owner_only_and_invalidates_cache(container):
    link = await _link(container)
    assert not await container.links.delete_owned(link.code, owner_id=999)
    assert await container.links.delete_owned(link.code, owner_id=10)
    assert await container.links.get(link.code) is None


async def test_owner_page_summaries(container):
    link = await _link(container, max_downloads=5)
    await container.links.reserve_download(link)
    items, total, page = await container.links.owned_page(10, page=7, page_size=5)
    assert (total, page) == (1, 0)  # out-of-range page is clamped
    summary = items[0]
    assert summary.download_count == 1 and summary.media_count == 3 and summary.total_size == 3 * 1024
    assert summary.type_counts == {MediaType.PHOTO: 1, MediaType.VIDEO: 1, MediaType.AUDIO: 1}


async def test_access_log_groups_views_per_link(container):
    link = await _link(container)
    await container.users.ensure(20)
    for _ in range(3):
        await container.links.record_view(link, 20)
    rows, total = await container.links.access_log(20, page=0, page_size=10)
    assert total == 1 and rows[0].code == link.code and rows[0].view_count == 3
