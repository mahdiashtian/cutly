from __future__ import annotations

from collections import Counter
from datetime import datetime

from core.clock import utcnow
from core.enums import MediaType
from schemas.base import BaseDTO


class MediaItem(BaseDTO):
    """A Telegram media reference, as captured at upload time."""

    media_type: MediaType
    size: int
    tg_file_id: int
    tg_access_hash: int
    tg_file_reference: bytes
    storage_message_id: int


class MediaDTO(MediaItem):
    id: int
    position: int


class LinkDTO(BaseDTO):
    """Everything needed to serve a link; this is the cached shape.

    ``download_count`` is intentionally *not* here: it changes on every download
    and is reserved atomically in SQL, so a cached copy would only be wrong.
    """

    id: int
    code: str
    owner_id: int
    caption: str | None
    password_hash: str | None
    expires_at: datetime | None
    max_downloads: int | None
    created_at: datetime
    media: list[MediaDTO]

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= utcnow()


class LinkSummary(BaseDTO):
    """Owner-facing view of a link (history, tracking): fresh from SQL."""

    code: str
    caption: str | None
    has_password: bool
    expires_at: datetime | None
    max_downloads: int | None
    download_count: int
    created_at: datetime
    total_size: int
    type_counts: dict[MediaType, int]

    @property
    def media_count(self) -> int:
        return sum(self.type_counts.values())


def count_types(items: list[MediaItem]) -> dict[MediaType, int]:
    return dict(Counter(item.media_type for item in items))
