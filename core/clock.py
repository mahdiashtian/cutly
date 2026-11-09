"""Time helpers. Everything is stored in UTC; only the UI uses the local zone."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; they are UTC by construction."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_local(text: str, zone: str, fmt: str = "%Y-%m-%d %H:%M") -> datetime:
    """Parse an admin-typed local time and return it in UTC."""
    return datetime.strptime(text.strip(), fmt).replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)


def format_local(value: datetime | None, zone: str, fmt: str = "%Y/%m/%d %H:%M") -> str | None:
    if value is None:
        return None
    return as_utc(value).astimezone(ZoneInfo(zone)).strftime(fmt)
