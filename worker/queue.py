"""Enqueueing background jobs, by task *name*.

The bot imports only this module (not the task code), so it stays decoupled
from the worker. ``send_task`` does network I/O to Redis; it runs in a thread
so the bot's event loop is never blocked, not even for a millisecond.
"""
from __future__ import annotations

import asyncio

from celery import Celery

DEFAULT_QUEUE = "default"
BROADCAST_QUEUE = "broadcasts"


class TaskName:
    DELETE_MESSAGES = "cutly.delete_messages"
    RUN_BROADCAST = "cutly.run_broadcast"
    DISPATCH_BROADCASTS = "cutly.dispatch_broadcasts"
    DATA_BACKUP = "cutly.data_backup"
    FULL_BACKUP = "cutly.full_backup"
    STAGE_RESTORE = "cutly.stage_restore"
    APPLY_RESTORE = "cutly.apply_restore"
    CLEANUP_FILES = "cutly.cleanup_files"
    REFRESH_CHANNEL_TITLES = "cutly.refresh_channel_titles"


class TaskQueue:
    def __init__(self, celery: Celery) -> None:
        self._celery = celery

    async def _send(self, name: str, *args, countdown: float | None = None) -> None:
        await asyncio.to_thread(self._celery.send_task, name, args=args, countdown=countdown)

    async def delete_messages_later(self, chat_id: int, message_ids: list[int], delay: int) -> None:
        await self._send(TaskName.DELETE_MESSAGES, chat_id, message_ids, countdown=delay)

    async def run_broadcast(self, broadcast_id: int) -> None:
        await self._send(TaskName.RUN_BROADCAST, broadcast_id)

    async def dispatch_broadcasts(self) -> None:
        await self._send(TaskName.DISPATCH_BROADCASTS)

    async def data_backup(self, admin_id: int) -> None:
        await self._send(TaskName.DATA_BACKUP, admin_id)

    async def full_backup(self, admin_id: int) -> None:
        await self._send(TaskName.FULL_BACKUP, admin_id)

    async def stage_restore(self, admin_id: int, upload_path: str) -> None:
        await self._send(TaskName.STAGE_RESTORE, admin_id, upload_path)

    async def apply_restore(self, admin_id: int, staged_json: str) -> None:
        await self._send(TaskName.APPLY_RESTORE, admin_id, staged_json)
