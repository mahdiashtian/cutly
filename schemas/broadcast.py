from __future__ import annotations

from datetime import datetime

from core.enums import BroadcastAudience, BroadcastMode, BroadcastStatus
from schemas.base import BaseDTO


class BroadcastDTO(BaseDTO):
    id: int
    admin_id: int
    mode: BroadcastMode
    audience: BroadcastAudience
    channel_ref: str | None
    source_chat_id: int | None
    source_message_id: int | None
    status: BroadcastStatus
    cancel_requested: bool
    scheduled_at: datetime | None
    cursor: int | None
    total: int
    succeeded: int
    failed: int
    status_message_id: int | None


class Recipient(BaseDTO):
    id: int
    access_hash: int | None


class DashboardStats(BaseDTO):
    total_users: int
    new_today: int
    week_growth: int
    total_links: int
    links_today: int
    downloads: int
    views_today: int
    broadcasts: int
    delivery_rate: float
