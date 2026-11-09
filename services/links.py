from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from core.clock import utcnow
from core.security import hash_password, new_share_code, verify_password
from repositories.postgres.unit_of_work import UnitOfWorkFactory
from repositories.redis.caches import LinkCache
from schemas.link import LinkDTO, LinkSummary, MediaItem
from schemas.user import UserAccessRow
from services.base import Service

_CODE_ATTEMPTS = 5


class LinkService(Service):
    def __init__(self, uow: UnitOfWorkFactory, cache: LinkCache) -> None:
        super().__init__(uow)
        self._cache = cache

    # ---- reads ----
    async def get(self, code: str) -> LinkDTO | None:
        async def read_db() -> LinkDTO | None:
            async with self._uow() as uow:
                return await uow.links.get_by_code(code)

        async def write_cache(link: LinkDTO | None) -> None:
            if link is None:
                await self._cache.set_absent(code)
            else:
                await self._cache.set(link)

        return await self._cached(read_cache=lambda: self._cache.get(code), read_db=read_db,
                                  write_cache=write_cache)

    async def get_owned(self, code: str, owner_id: int) -> LinkDTO | None:
        link = await self.get(code)
        return link if link is not None and link.owner_id == owner_id else None

    async def owned_summary(self, code: str, owner_id: int) -> LinkSummary | None:
        async with self._uow() as uow:
            return await uow.links.owned_summary(code, owner_id)

    async def owned_page(self, owner_id: int, page: int, page_size: int) -> tuple[list[LinkSummary], int, int]:
        """``(items, total, page)``; an out-of-range page is clamped to the last one."""
        async with self._uow() as uow:
            total = await uow.links.count_owned(owner_id)
            page = min(max(page, 0), max(0, (total - 1) // page_size))
            items = await uow.links.owned_page(owner_id, offset=page * page_size, limit=page_size)
        return items, total, page

    async def count_owned(self, owner_id: int) -> int:
        async with self._uow() as uow:
            return await uow.links.count_owned(owner_id)

    async def access_log(self, viewer_id: int, page: int, page_size: int) -> tuple[list[UserAccessRow], int]:
        async with self._uow() as uow:
            return await uow.links.viewer_page(viewer_id, offset=page * page_size, limit=page_size)

    # ---- writes ----
    async def create(
        self, owner_id: int, media: list[MediaItem], *,
        expires_at: datetime | None, max_downloads: int | None,
    ) -> LinkDTO:
        """Persist a link and all of its media in one transaction."""
        for attempt in range(_CODE_ATTEMPTS):
            try:
                async with self._uow() as uow:
                    link = await uow.links.create(
                        code=new_share_code(), owner_id=owner_id, expires_at=expires_at,
                        max_downloads=max_downloads, media=media,
                    )
            except IntegrityError:
                # 62**15 codes make a collision astronomically rare, but not impossible.
                if attempt == _CODE_ATTEMPTS - 1:
                    raise
                continue
            await self._safe(self._cache.set(link))
            return link
        raise AssertionError("unreachable")

    async def delete_owned(self, code: str, owner_id: int) -> bool:
        async with self._uow() as uow:
            deleted = await uow.links.delete_owned(code, owner_id)
        if deleted:
            await self._safe(self._cache.invalidate(code))
        return deleted

    async def set_caption(self, link: LinkDTO, caption: str | None) -> None:
        await self._update(link, caption=caption)

    async def set_password(self, link: LinkDTO, password: str | None) -> None:
        hashed = await asyncio.to_thread(hash_password, password) if password else None
        await self._update(link, password_hash=hashed)

    async def check_password(self, link: LinkDTO, password: str) -> bool:
        if link.password_hash is None:
            return True
        return await asyncio.to_thread(verify_password, password, link.password_hash)

    async def _update(self, link: LinkDTO, **values) -> None:
        async with self._uow() as uow:
            await uow.links.update(link.id, **values)
            fresh = await uow.links.get_by_code(link.code)
        if fresh is not None:
            await self._safe(self._cache.set(fresh))  # write-through

    async def refresh_media_reference(
        self, link: LinkDTO, media_id: int, access_hash: int, file_reference: bytes
    ) -> None:
        async with self._uow() as uow:
            await uow.links.update_media_reference(media_id, access_hash, file_reference)
        await self._safe(self._cache.invalidate(link.code))

    # ---- downloads ----
    async def reserve_download(self, link: LinkDTO) -> int | None:
        async with self._uow() as uow:
            return await uow.links.reserve_download(link.id, utcnow())

    async def release_download(self, link: LinkDTO) -> None:
        async with self._uow() as uow:
            await uow.links.release_download(link.id)

    async def record_view(self, link: LinkDTO, viewer_id: int) -> None:
        async with self._uow() as uow:
            await uow.links.add_view(link.id, viewer_id)
