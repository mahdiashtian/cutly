"""Importing this package registers every table on ``Base.metadata``.

Code that walks all tables uses ``Base.metadata.sorted_tables`` (parents first).
"""
from db.models.broadcast import Broadcast
from db.models.channel import MandatoryChannel
from db.models.link import Link, LinkMedia, LinkView
from db.models.settings import SETTINGS_ROW_ID, BotSettings
from db.models.user import User

__all__ = [
    "SETTINGS_ROW_ID",
    "BotSettings",
    "Broadcast",
    "Link",
    "LinkMedia",
    "LinkView",
    "MandatoryChannel",
    "User",
]
