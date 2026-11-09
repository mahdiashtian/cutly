from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update

from core.enums import MediaType
from db.models import Link, LinkMedia, LinkView
from repositories.postgres.base import SqlRepository
from schemas.link import LinkDTO, LinkSummary, MediaItem
from schemas.user import UserAccessRow


class LinkRepository(SqlRepository):
    # ---- reads ----
    async def get_by_code(self, code: str) -> LinkDTO | None:
        row = await self._session.scalar(select(Link).where(Link.code == code))
        return LinkDTO.model_validate(row) if row else None

    async def count_owned(self, owner_id: int) -> int:
        return int(await self._session.scalar(
            select(func.count()).select_from(Link).where(Link.owner_id == owner_id)
        ))

    async def owned_page(self, owner_id: int, *, offset: int, limit: int) -> list[LinkSummary]:
        links = await self._session.scalars(
            select(Link).where(Link.owner_id == owner_id)
            .order_by(Link.created_at.desc(), Link.id.desc()).offset(offset).limit(limit)
        )
        return await self._summaries(list(links))

    async def owned_summary(self, code: str, owner_id: int) -> LinkSummary | None:
        link = await self._session.scalar(select(Link).where(Link.code == code, Link.owner_id == owner_id))
        summaries = await self._summaries([link] if link else [])
        return summaries[0] if summaries else None

    async def _summaries(self, links: list[Link]) -> list[LinkSummary]:
        """Media totals for many links in ONE grouped query, never one per link."""
        if not links:
            return []
        stats = await self._session.execute(
            select(LinkMedia.link_id, LinkMedia.media_type, func.count(), func.sum(LinkMedia.size))
            .where(LinkMedia.link_id.in_([link.id for link in links]))
            .group_by(LinkMedia.link_id, LinkMedia.media_type)
        )
        type_counts: dict[int, dict[MediaType, int]] = defaultdict(dict)
        sizes: dict[int, int] = defaultdict(int)
        for link_id, media_type, count, size in stats:
            type_counts[link_id][MediaType(media_type)] = count
            sizes[link_id] += int(size or 0)
        return [
            LinkSummary(
                code=link.code, caption=link.caption, has_password=link.password_hash is not None,
                expires_at=link.expires_at, max_downloads=link.max_downloads,
                download_count=link.download_count, created_at=link.created_at,
                total_size=sizes[link.id], type_counts=type_counts[link.id],
            )
            for link in links
        ]

    # ---- writes ----
    async def create(
        self, *, code: str, owner_id: int, expires_at: datetime | None,
        max_downloads: int | None, media: list[MediaItem],
    ) -> LinkDTO:
        link = Link(
            code=code, owner_id=owner_id, expires_at=expires_at, max_downloads=max_downloads,
            download_count=0,
            media=[LinkMedia(position=index, **item.model_dump()) for index, item in enumerate(media)],
        )
        self._session.add(link)
        await self._session.flush()
        await self._session.refresh(link, attribute_names=["created_at"])
        return LinkDTO.model_validate(link)

    async def update(self, link_id: int, **values) -> None:
        await self._session.execute(update(Link).where(Link.id == link_id).values(**values))

    async def delete_owned(self, code: str, owner_id: int) -> bool:
        result = await self._session.execute(delete(Link).where(Link.code == code, Link.owner_id == owner_id))
        return bool(result.rowcount)

    async def update_media_reference(self, media_id: int, access_hash: int, file_reference: bytes) -> None:
        await self._session.execute(
            update(LinkMedia).where(LinkMedia.id == media_id)
            .values(tg_access_hash=access_hash, tg_file_reference=file_reference)
        )

    # ---- download counter ----
    async def reserve_download(self, link_id: int, now: datetime) -> int | None:
        """Take one download slot atomically; ``None`` when expired or exhausted.

        The check and the increment are one UPDATE, so concurrent requests from
        any number of processes can never exceed ``max_downloads``. (The old code
        reserved slots in process memory, which only held for a single process.)
        """
        result = await self._session.execute(
            update(Link)
            .where(
                Link.id == link_id,
                or_(Link.expires_at.is_(None), Link.expires_at > now),
                or_(Link.max_downloads.is_(None), Link.download_count < Link.max_downloads),
            )
            .values(download_count=Link.download_count + 1)
            .returning(Link.download_count)
        )
        return result.scalar_one_or_none()

    async def release_download(self, link_id: int) -> None:
        """Give back a reserved slot whose delivery failed."""
        await self._session.execute(
            update(Link).where(Link.id == link_id, Link.download_count > 0)
            .values(download_count=Link.download_count - 1)
        )

    # ---- access log ----
    async def add_view(self, link_id: int, viewer_id: int) -> None:
        self._session.add(LinkView(link_id=link_id, viewer_id=viewer_id))

    async def viewer_page(self, viewer_id: int, *, offset: int, limit: int) -> tuple[list[UserAccessRow], int]:
        total = await self._session.scalar(
            select(func.count(func.distinct(LinkView.link_id))).where(LinkView.viewer_id == viewer_id)
        )
        last_viewed = func.max(LinkView.viewed_at).label("last_viewed")
        rows = await self._session.execute(
            select(Link.code, func.count(LinkView.id).label("view_count"), last_viewed)
            .join(Link, Link.id == LinkView.link_id)
            .where(LinkView.viewer_id == viewer_id)
            .group_by(Link.code)
            .order_by(last_viewed.desc())
            .offset(offset).limit(limit)
        )
        return [UserAccessRow.model_validate(row, from_attributes=True) for row in rows], int(total or 0)
