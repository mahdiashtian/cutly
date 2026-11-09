"""One logging setup shared by the bot and the Celery worker."""
from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(format=_FORMAT, level=level.upper())
    # Telethon logs every reconnect at INFO; keep our own logs readable.
    logging.getLogger("telethon").setLevel(logging.WARNING)
