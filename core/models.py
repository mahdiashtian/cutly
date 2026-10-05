"""SQLAlchemy mappings compatible with existing Cutly database rows."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    false,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Keep UTC-aware timestamps on both SQLite and PostgreSQL."""

    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self):
        return datetime

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        Index("ix_user_is_superuser_is_staff", "is_superuser", "is_staff"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    userid: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, index=True
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), index=True
    )
    is_staff: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), index=True
    )
    files: Mapped[list[File]] = relationship(
        back_populates="owner", passive_deletes=True, lazy="raise"
    )


class Channel(Base):
    __tablename__ = "channel"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    channel_link: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), index=True
    )


class File(Base):
    __tablename__ = "file"
    __table_args__ = (
        Index("ix_file_owner_id_created_at", "owner_id", "created_at"),
        Index("ix_file_type_created_at", "type", "created_at"),
        Index("ix_file_album_id_album_order", "album_id", "album_order"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(BigInteger)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    file_id: Mapped[int] = mapped_column(BigInteger)
    access_hash: Mapped[int] = mapped_column(BigInteger)
    file_reference: Mapped[bytes] = mapped_column(LargeBinary)
    message_id: Mapped[int] = mapped_column(BigInteger)
    count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", index=True
    )
    password: Mapped[str | None] = mapped_column(String(255))
    caption: Mapped[str | None] = mapped_column(Text)
    album_id: Mapped[str | None] = mapped_column(String(64), index=True)
    album_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    max_downloads: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user.userid", ondelete="CASCADE")
    )
    owner: Mapped[User] = relationship(back_populates="files", lazy="raise")


class FileAccessLog(Base):
    __tablename__ = "file_access_log"
    __table_args__ = (
        Index("ix_file_access_log_viewer_id_accessed_at", "viewer_id", "accessed_at"),
        Index("ix_file_access_log_viewer_id_file_code", "viewer_id", "file_code"),
        Index("ix_file_access_log_file_code_accessed_at", "file_code", "accessed_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    viewer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    file_code: Mapped[str] = mapped_column(String(32), index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    accessed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, index=True
    )


class BotSettings(Base):
    __tablename__ = "bot_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    global_caption: Mapped[str | None] = mapped_column(Text)
    show_file_captions: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )


class BroadcastJob(Base):
    __tablename__ = "broadcast_job"
    __table_args__ = (
        Index("ix_broadcast_job_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_broadcast_job_admin_id_started_at", "admin_id", "started_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    delivery_type: Mapped[str] = mapped_column(String(16))
    audience: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16), default="scheduled", server_default="scheduled", index=True
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    success_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
