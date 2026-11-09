from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import MediaType, enum_values
from db.base import Base, BigIntPK, CreatedAtMixin, UTCDateTime


class Link(CreatedAtMixin, Base):
    """One share link. Its settings (caption, password, limits, counter) apply to
    every item behind it.

    The old schema copied these settings onto every file row of an album and
    told parts apart with ``CODE_partN`` codes; one link row removes both the
    duplication and the string hack.
    """

    __tablename__ = "links"
    __table_args__ = (
        UniqueConstraint("code", name="uq_links_code"),
        CheckConstraint("max_downloads IS NULL OR max_downloads > 0", name="ck_links_max_downloads"),
        CheckConstraint("download_count >= 0", name="ck_links_download_count"),
        Index("ix_links_owner_id_created_at", "owner_id", "created_at"),
        Index("ix_links_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    caption: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    max_downloads: Mapped[int | None] = mapped_column(Integer)
    download_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)

    media: Mapped[list[LinkMedia]] = relationship(
        back_populates="link",
        order_by="LinkMedia.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class LinkMedia(Base):
    """A Telegram media item behind a link, addressed by its file id/hash/reference
    so it can be re-sent without downloading or re-uploading."""

    __tablename__ = "link_media"
    # The unique key doubles as the index for "all media of a link, in order".
    __table_args__ = (UniqueConstraint("link_id", "position", name="uq_link_media_link_id_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[int] = mapped_column(Integer, ForeignKey("links.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger)
    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType, name="media_type", native_enum=False, create_constraint=True,
             length=16, values_callable=enum_values)
    )
    size: Mapped[int] = mapped_column(BigInteger)
    tg_file_id: Mapped[int] = mapped_column(BigInteger)
    tg_access_hash: Mapped[int] = mapped_column(BigInteger)
    tg_file_reference: Mapped[bytes] = mapped_column(LargeBinary)
    # The copy in the storage channel, used to refresh an expired file reference.
    storage_message_id: Mapped[int] = mapped_column(BigInteger)

    link: Mapped[Link] = relationship(back_populates="media")


class LinkView(Base):
    """One successful delivery of a link to a viewer (the admin's access log)."""

    __tablename__ = "link_views"
    __table_args__ = (
        # Covers the per-viewer log: GROUP BY link ORDER BY last view.
        Index("ix_link_views_viewer_id_link_id_viewed_at", "viewer_id", "link_id", "viewed_at"),
        # Lets a link delete cascade without a sequential scan.
        Index("ix_link_views_link_id", "link_id"),
        # "Views in the last 24 hours" on the dashboard.
        Index("ix_link_views_viewed_at", "viewed_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    link_id: Mapped[int] = mapped_column(Integer, ForeignKey("links.id", ondelete="CASCADE"))
    viewer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    viewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
