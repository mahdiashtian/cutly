"""Bridge between Celery's synchronous tasks and our asyncio code.

Celery tasks are plain functions, but every service is async. Each worker
process therefore owns ONE event loop, ONE Container (DB + Redis pools) and ONE
Telegram client, created lazily on the first task and reused by every task
after it. Creating them per task would mean a new connection pool and a new
Telegram login for every message deletion.

The Telegram client uses its own in-memory session (a separate authorisation
from the bot's), so it never competes with the bot for its session file or its
updates; ``receive_updates=False`` makes it a pure sender.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from celery.signals import worker_process_shutdown, worker_shutdown
from telethon import TelegramClient
from telethon.sessions import StringSession

from bot.telegram import build_client
from container import Container
from core.config import get_settings
from worker.app import celery_app
from worker.queue import TaskQueue

T = TypeVar("T")


class WorkerRuntime:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._container: Container | None = None
        self._client: TelegramClient | None = None
        self.queue = TaskQueue(celery_app)

    def run(self, job: Callable[[WorkerRuntime], Awaitable[T]]) -> T:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop.run_until_complete(job(self))

    async def container(self) -> Container:
        if self._container is None:
            container = Container(get_settings())
            await container.startup()
            self._container = container
        return self._container

    async def telegram(self) -> TelegramClient:
        if self._client is None:
            settings = get_settings()
            # flood_sleep_threshold=0: floods raise, so a broadcast can pause
            # *all* of its sends instead of one coroutine sleeping silently.
            client = build_client(settings, session=StringSession(), receive_updates=False,
                                  flood_sleep_threshold=0)
            await client.start(bot_token=settings.bot_token)
            self._client = client
        return self._client

    def close(self) -> None:
        if self._loop is None:
            return

        async def shutdown() -> None:
            if self._client is not None:
                await self._client.disconnect()
            if self._container is not None:
                await self._container.shutdown()

        self._loop.run_until_complete(shutdown())
        self._loop.close()
        self._loop = None


runtime = WorkerRuntime()


@worker_process_shutdown.connect  # prefork pool: each child process
@worker_shutdown.connect          # solo pool: tasks run in the main process
def _close_runtime(**_kwargs) -> None:
    runtime.close()
