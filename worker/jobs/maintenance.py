"""Small periodic and fire-and-forget jobs."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from telethon import TelegramClient

from container import Container

log = logging.getLogger(__name__)

# Temporary files and how long an orphan may stay before it is removed.
# Data/full/safety backups are never touched: keeping them is the operator's call.
_TEMPORARY_FILES = {"upload-*": 3600, "staging-*": 3600, "broadcast-*.csv": 7 * 86400}


async def delete_messages(client: TelegramClient, message_ids: list[int]) -> None:
    # entity=None deletes private-chat messages directly, without resolving the peer.
    await client.delete_messages(None, message_ids)


async def dispatch_broadcasts(container: Container, enqueue) -> list[int]:
    if await container.maintenance.is_on():
        return []
    ids = await container.broadcasts.collect_runnable()
    for broadcast_id in ids:
        await enqueue(broadcast_id)
    return ids


def cleanup_files(directory: Path) -> int:
    removed, now = 0, time.time()
    for pattern, max_age in _TEMPORARY_FILES.items():
        for path in directory.glob(pattern):
            if now - path.stat().st_mtime > max_age:
                path.unlink(missing_ok=True)
                removed += 1
    return removed


async def refresh_channel_titles(container: Container, client: TelegramClient) -> None:
    """Titles shown on join buttons follow channel renames."""
    for channel in await container.channels.list():
        try:
            entity = await client.get_entity(channel.peer)
        except Exception as error:  # noqa: BLE001 - keep the stored title
            log.warning("cannot resolve channel %s: %s", channel.chat_ref, error)
            continue
        title = getattr(entity, "title", None)
        if title and title != channel.title:
            await container.channels.set_title(channel.id, title)
