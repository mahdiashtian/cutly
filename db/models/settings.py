from __future__ import annotations

from sqlalchemy import Boolean, Integer, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

SETTINGS_ROW_ID = 1


class BotSettings(Base):
    """Singleton row of admin-editable settings (always ``id == 1``)."""

    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    global_caption: Mapped[str | None] = mapped_column(Text)
    show_file_captions: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
