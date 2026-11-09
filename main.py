"""Bot process entrypoint: ``python main.py``.

Background work (broadcasts, deletions, backups, restores) runs in the Celery
worker; see ``worker/app.py`` for the worker and beat commands.
"""
from __future__ import annotations

import asyncio
import logging

from bot.app import BotApp
from bot.dispatcher import Dispatcher
from bot.handlers import build_router
from bot.telegram import build_client
from container import Container
from core.config import Settings, get_settings
from core.logs import setup_logging
from db.migrations import assert_schema_is_current
from worker.app import celery_app
from worker.queue import TaskQueue

log = logging.getLogger("cutly")


def _require(settings: Settings) -> None:
    missing = [name.upper() for name in ("api_id", "api_hash", "bot_token") if not getattr(settings, name)]
    if missing:
        raise SystemExit("missing required settings: " + ", ".join(missing))


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    _require(settings)

    container = Container(settings)
    await container.startup()
    client = build_client(settings)
    try:
        await assert_schema_is_current(container.database.engine)
        await container.warm_cache()
        app = BotApp(container, client, TaskQueue(celery_app))
        Dispatcher(app, build_router()).register()

        await client.start(bot_token=settings.bot_token)
        me = await client.get_me()
        app.username = me.username or ""
        log.info("bot started as @%s", app.username)
        try:
            await client.catch_up()  # answer what arrived while we were down
        except Exception:  # noqa: BLE001 - best effort; never block startup on it
            log.warning("catch-up failed; continuing", exc_info=True)
        await client.run_until_disconnected()
    finally:
        await client.disconnect()
        await container.shutdown()
        log.info("shutdown complete")


def main() -> None:
    # uvloop is a faster event loop; it has no Windows build, so fall back.
    try:
        import uvloop
    except ModuleNotFoundError:
        asyncio.run(run())
    else:
        uvloop.run(run())


if __name__ == "__main__":
    main()
