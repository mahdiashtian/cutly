"""Declarative base and the column types shared by every model."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """``Base.metadata`` is the schema Alembic migrations must produce."""


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC, on PostgreSQL *and* SQLite.

    SQLite has no timezone support and hands back naive values; without this a
    comparison between a stored and a fresh ``datetime`` would raise.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# A 64-bit surrogate key on PostgreSQL. SQLite only auto-increments a column
# declared exactly ``INTEGER PRIMARY KEY`` (which is 64-bit there anyway).
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
