from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Enum, Index, Integer, String, false, text
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import BroadcastAudience, BroadcastMode, BroadcastStatus, enum_values
from db.base import Base, CreatedAtMixin, UTCDateTime


def _enum(enum, name: str) -> Enum:
    return Enum(enum, name=name, native_enum=False, create_constraint=True,
                length=16, values_callable=enum_values)


class Broadcast(CreatedAtMixin, Base):
    """A durable broadcast job.

    It used to live in process memory (lost on restart). As a row it survives
    restarts, can be scheduled, checkpoints its progress (``cursor``) so a crashed
    worker resumes instead of starting over, and is cancelled through the
    database from any process.
    """

    __tablename__ = "broadcasts"
    __table_args__ = (
        Index("ix_broadcasts_status_scheduled_at", "status", "scheduled_at"),
        # At most one RUNNING broadcast, enforced by the database itself so two
        # workers can never send at the same time.
        Index(
            "uq_broadcasts_single_running", "status", unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[BroadcastMode] = mapped_column(_enum(BroadcastMode, "broadcast_mode"))
    audience: Mapped[BroadcastAudience] = mapped_column(_enum(BroadcastAudience, "broadcast_audience"))
    channel_ref: Mapped[str | None] = mapped_column(String(255))
    # The admin's own message that is copied or forwarded.
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[BroadcastStatus] = mapped_column(_enum(BroadcastStatus, "broadcast_status"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Last user id processed: users are walked in id order (keyset pagination).
    cursor: Mapped[int | None] = mapped_column(BigInteger)
    total: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    succeeded: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    failed: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    status_message_id: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
