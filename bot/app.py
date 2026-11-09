"""What every bot handler can reach: services, the Telegram client, the job queue."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from telethon import TelegramClient

from bot.delivery import LinkDelivery
from container import Container
from core.clock import format_local
from core.config import Settings
from worker.queue import TaskQueue


@dataclass
class BotApp:
    container: Container
    client: TelegramClient
    tasks: TaskQueue
    username: str = ""
    delivery: LinkDelivery = field(init=False)

    def __post_init__(self) -> None:
        self.delivery = LinkDelivery(
            self.client, self.container.links, storage_channel_id=self.settings.storage_channel_id
        )

    @property
    def settings(self) -> Settings:
        return self.container.settings

    def share_url(self, code: str) -> str:
        return f"https://t.me/{self.username}?start=get_{code}"

    def local_time(self, value: datetime | None) -> str | None:
        return format_local(value, self.settings.timezone)

    async def is_admin(self, user_id: int) -> bool:
        return await self.container.users.is_admin(user_id)
