from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Index, false
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, CreatedAtMixin, UTCDateTime


class User(CreatedAtMixin, Base):
    """A Telegram user who talked to the bot.

    The Telegram id *is* the primary key: it is immutable and every lookup is by
    it, so the old ``id`` + unique ``userid`` pair was one index too many.
    """

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # The bot-specific access hash lets any process (e.g. a Celery worker with a
    # fresh session) address this user without an extra users.getUsers call.
    access_hash: Mapped[int | None] = mapped_column(BigInteger)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    last_active_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
