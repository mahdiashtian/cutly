from __future__ import annotations

from datetime import datetime

from schemas.base import BaseDTO


class UserDTO(BaseDTO):
    """Cached user. ``last_active_at`` is deliberately absent: it changes all the
    time, is only read by SQL audience queries, and would make the cache stale."""

    id: int
    access_hash: int | None
    is_admin: bool
    created_at: datetime


class UserProfile(BaseDTO):
    """Fresh-from-SQL details for the admin (never cached)."""

    id: int
    created_at: datetime
    last_active_at: datetime | None


class UserAccessRow(BaseDTO):
    """One line of the admin's per-user access log."""

    code: str
    view_count: int
    last_viewed: datetime
