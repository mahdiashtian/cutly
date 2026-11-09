"""Run the whole project: ``python main.py``.

1. upgrade the database schema (once, before anything else touches it);
2. start the Celery worker and beat processes (unless EMBEDDED_WORKERS=false);
3. run the bot until it is stopped (Ctrl+C), then stop the workers.

The databases themselves run in Docker: ``docker compose up -d``.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from bot.app import BotApp
from bot.dispatcher import Dispatcher
from bot.handlers import build_router
from bot.telegram import build_client
from container import Container
from core.config import Settings, get_settings
from core.logs import setup_logging
from db.migrations import upgrade_to_head
from worker.app import celery_app
from worker.processes import ProcessGroup, celery_processes
from worker.queue import TaskQueue

log = logging.getLogger("cutly")


def _require(settings: Settings) -> None:
    missing = [name.upper() for name in ("api_id", "api_hash", "bot_token") if not getattr(settings, name)]
    if missing:
        raise SystemExit("missing required settings: " + ", ".join(missing))


async def run_bot(container: Container, settings: Settings) -> None:
    client = build_client(settings)
    app = BotApp(container, client, TaskQueue(celery_app))
    Dispatcher(app, build_router()).register()
    try:
        await client.start(bot_token=settings.bot_token)
        app.username = (await client.get_me()).username or ""
        log.info("bot started as @%s", app.username)
        try:
            await client.catch_up()  # answer what arrived while we were down
        except Exception:  # noqa: BLE001 - best effort; never block startup on it
            log.warning("catch-up failed; continuing", exc_info=True)
        await client.run_until_disconnected()
    finally:
        await client.disconnect()


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    _require(settings)

    if settings.admin_master is None:
        log.warning("ADMIN_MASTER is not set: owner-only features (admins, backups, restore) are disabled")
    container = Container(settings)
    await container.startup()
    workers = ProcessGroup(celery_processes(settings) if settings.embedded_workers else [])
    try:
        await upgrade_to_head(container.database.engine)
        await container.warm_cache()
        await workers.start()
        await run_bot(container, settings)
    finally:
        await workers.stop()
        await container.shutdown()
        log.info("shutdown complete")


def main() -> None:
    # uvloop is a faster event loop; it has no Windows build, so fall back.
    try:
        import uvloop
        runner = uvloop.run
    except ModuleNotFoundError:
        runner = asyncio.run
    # Ctrl+C: run() has already stopped the workers in its finally block.
    with contextlib.suppress(KeyboardInterrupt):
        runner(run())


if __name__ == "__main__":
    main()
