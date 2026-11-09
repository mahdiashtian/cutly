"""Closed sets of values stored in the database.

They are ``StrEnum`` so a member compares equal to its stored string and
serialises to it in JSON (cache payloads, backups) without extra code.
"""
from __future__ import annotations

from enum import StrEnum


class MediaType(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    ANIMATION = "animation"
    AUDIO = "audio"
    VOICE = "voice"
    STICKER = "sticker"
    DOCUMENT = "document"

    @property
    def groups_in_album(self) -> bool:
        """Telegram only mixes photos and videos inside one album."""
        return self in (MediaType.PHOTO, MediaType.VIDEO)


class BroadcastMode(StrEnum):
    COPY = "copy"
    FORWARD = "forward"


class BroadcastAudience(StrEnum):
    ALL = "all"
    NEW = "new"            # joined in the last 7 days
    ACTIVE = "active"      # active in the last 30 days
    INACTIVE = "inactive"  # not active in the last 30 days
    CHANNEL = "channel"    # members of a given channel (checked while sending)


class BroadcastStatus(StrEnum):
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def is_active(self) -> bool:
        return self in (BroadcastStatus.SCHEDULED, BroadcastStatus.QUEUED, BroadcastStatus.RUNNING)


def enum_values(enum: type[StrEnum]) -> list[str]:
    """Used by SQLAlchemy so the *value* (not the member name) is stored."""
    return [member.value for member in enum]
