"""Bot initialization and lifecycle management."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import API_HASH, API_ID, BOT_TOKEN, SESSION_NAME, SESSION_STRING, WORKERS
from core import State, close_db, init_db
from core.models import File
from services import userid_list

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)


# Bot client instance
if SESSION_STRING:
    CLIENT = TelegramClient(
        StringSession(SESSION_STRING), API_ID, API_HASH, workers=WORKERS
    )
else:
    CLIENT = TelegramClient(SESSION_NAME, API_ID, API_HASH)

CLIENT.parse_mode = "md"

# Global state management
CONVERSATION_STATE: Dict[int, Optional[State]] = {}
CONVERSATION_OBJECT: Dict[int, Optional[File]] = {}
LIST_VIDEO: List[Dict[str, int]] = []
USER_LIST: List[int] = []
CHANNEL_JOIN_LIST: Optional[Dict[str, Dict[str, str]]] = None
BOT_USERNAME: str = ""

# Scheduler
SCHEDULER = AsyncIOScheduler()


async def start_bot() -> None:
    """Initialize bot, database, and start scheduler."""
    
    global USER_LIST, BOT_USERNAME
    
    LOGGER.info("Initializing database...")
    await init_db()
    
    LOGGER.info("Loading user list...")
    USER_LIST = list(await userid_list())
    
    LOGGER.info("Starting Telegram client...")
    await CLIENT.start(bot_token=BOT_TOKEN)
    
    me = await CLIENT.get_me()
    BOT_USERNAME = (me.username or "").lstrip("@")
    LOGGER.info(f"Bot started as @{BOT_USERNAME}")


async def stop_bot() -> None:
    """Stop scheduler and close database connections."""
    
    LOGGER.info("Shutting down scheduler...")
    SCHEDULER.shutdown()
    
    LOGGER.info("Closing database connections...")
    await close_db()
    
    LOGGER.info("Bot stopped successfully")


async def run_bot() -> None:
    """Run the bot until disconnected."""
    
    try:
        LOGGER.info("Bot is running. Press Ctrl+C to stop.")
        await CLIENT.run_until_disconnected()
    finally:
        await stop_bot()

