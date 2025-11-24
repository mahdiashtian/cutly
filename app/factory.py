"""Factory pattern for bot initialization."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import API_HASH, API_ID, BOT_TOKEN, SESSION_NAME, SESSION_STRING, WORKERS

LOGGER = logging.getLogger(__name__)


class BotFactory:
    """Factory for creating and configuring Telegram bot instances.
    
    This implements the Factory Pattern to centralize bot creation logic
    and make it easier to test and configure.
    
    Examples:
        >>> factory = BotFactory()
        >>> client = factory.create_client()
        >>> scheduler = factory.create_scheduler()
    """

    def __init__(self) -> None:
        """Initialize bot factory."""
        self._client: Optional[TelegramClient] = None
        self._scheduler: Optional[AsyncIOScheduler] = None

    def create_client(self) -> TelegramClient:
        """Create and configure Telegram client.
        
        Returns:
            Configured TelegramClient instance.
            
        Examples:
            >>> factory = BotFactory()
            >>> client = factory.create_client()
        """
        if self._client is None:
            LOGGER.info("Creating Telegram client...")
            
            if SESSION_STRING:
                self._client = TelegramClient(
                    StringSession(SESSION_STRING),
                    API_ID,
                    API_HASH,
                    workers=WORKERS
                )
                LOGGER.info("Using session string for authentication")
            else:
                self._client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
                LOGGER.info(f"Using session file: {SESSION_NAME}")
            
            # Configure client
            self._client.parse_mode = "md"
            
        return self._client

    def create_scheduler(self) -> AsyncIOScheduler:
        """Create and configure APScheduler instance.
        
        Returns:
            Configured AsyncIOScheduler instance.
            
        Examples:
            >>> factory = BotFactory()
            >>> scheduler = factory.create_scheduler()
        """
        if self._scheduler is None:
            LOGGER.info("Creating scheduler...")
            self._scheduler = AsyncIOScheduler()
        
        return self._scheduler

    def get_client(self) -> Optional[TelegramClient]:
        """Get existing client instance.
        
        Returns:
            Existing TelegramClient or None if not created yet.
        """
        return self._client

    def get_scheduler(self) -> Optional[AsyncIOScheduler]:
        """Get existing scheduler instance.
        
        Returns:
            Existing AsyncIOScheduler or None if not created yet.
        """
        return self._scheduler

    def reset(self) -> None:
        """Reset factory state (useful for testing).
        
        Examples:
            >>> factory = BotFactory()
            >>> factory.create_client()
            >>> factory.reset()  # Clean up for next test
        """
        self._client = None
        self._scheduler = None


# Global factory instance
_factory = BotFactory()


def get_bot_factory() -> BotFactory:
    """Get global bot factory instance.
    
    Returns:
        Global BotFactory instance.
        
    Examples:
        >>> from app.factory import get_bot_factory
        >>> factory = get_bot_factory()
        >>> client = factory.create_client()
    """
    return _factory

