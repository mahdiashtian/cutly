"""Mandatory channel membership ("forced join")."""
from __future__ import annotations

import asyncio
import logging

from redis.exceptions import RedisError
from telethon import Button, TelegramClient, errors

from bot.keyboards import Btn
from container import Container
from schemas.channel import ChannelDTO

log = logging.getLogger(__name__)


class MembershipGuard:
    def __init__(self, container: Container, client: TelegramClient) -> None:
        self._container = container
        self._client = client

    async def missing_channels(self, user_id: int) -> list[ChannelDTO]:
        """Channels the user still has to join (an empty list means allowed).

        Without caching this is one Telegram request per channel on *every*
        command, so a positive answer is cached briefly. Any error counts as
        "not a member": an unreachable channel can never be bypassed.
        """
        channels = await self._container.channels.list()
        if not channels:
            return []
        fingerprint = self._container.channels.fingerprint(channels)
        marker = self._container.joined_marker
        try:
            if await marker.is_marked(user_id, fingerprint):
                return []
        except RedisError:
            log.warning("membership cache unavailable; asking Telegram", exc_info=True)

        results = await asyncio.gather(*(self._is_member(channel, user_id) for channel in channels))
        missing = [channel for channel, is_member in zip(channels, results, strict=True) if not is_member]
        if not missing:
            try:
                await marker.mark(user_id, fingerprint)
            except RedisError:
                log.warning("membership cache write failed", exc_info=True)
        return missing

    async def _is_member(self, channel: ChannelDTO, user_id: int) -> bool:
        try:
            await self._client.get_permissions(channel.peer, user_id)
            return True
        except errors.UserNotParticipantError:
            return False
        except Exception as error:  # noqa: BLE001 - fail closed on any other error
            log.warning("membership check failed for %s: %s", channel.chat_ref, error)
            return False


def join_buttons(missing: list[ChannelDTO], bot_username: str, start_payload: str = "") -> list:
    rows = [[Button.url(channel.title, channel.invite_link)] for channel in missing]
    # «عضو شدم» re-opens the bot with the deep link the user originally came with.
    url = f"https://t.me/{bot_username}" if bot_username else "https://t.me"
    if start_payload and bot_username:
        url = f"{url}?start={start_payload}"
    rows.append([Button.url(Btn.JOINED, url)])
    return rows
