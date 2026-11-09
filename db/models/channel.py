from __future__ import annotations

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, CreatedAtMixin


class MandatoryChannel(CreatedAtMixin, Base):
    """A channel users must join before using the bot.

    ``title`` is resolved from Telegram once, when the admin adds the channel
    (and refreshed periodically), instead of on every cache rebuild.
    """

    __tablename__ = "mandatory_channels"
    __table_args__ = (UniqueConstraint("chat_ref", name="uq_mandatory_channels_chat_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ``@name`` without the ``@`` for public channels, ``-100…`` for private ones.
    chat_ref: Mapped[str] = mapped_column(String(255))
    invite_link: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
