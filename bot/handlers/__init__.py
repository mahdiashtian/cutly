"""Handler modules. Each owns a ``Router``; they are merged into one here."""
from __future__ import annotations

from bot.handlers import admin, backups, broadcast, captions, channels, download, links, start, upload
from bot.router import Router


def build_router() -> Router:
    router = Router()
    for module in (start, download, upload, links, admin, channels, captions, broadcast, backups):
        router.include(module.router)
    return router
