"""Telethon client construction, shared by the bot and the worker."""
from __future__ import annotations

from telethon import TelegramClient
from telethon.sessions import Session, StringSession
from telethon.tl.types import InputPeerUser

from core.config import Settings


def user_peer(user_id: int, access_hash: int | None) -> InputPeerUser | int:
    """Address a user directly when we know the access hash (no lookup request);
    otherwise let Telethon resolve the bare id."""
    return InputPeerUser(user_id, access_hash) if access_hash is not None else user_id


def build_client(
    settings: Settings, *, session: Session | str | None = None,
    receive_updates: bool = True, flood_sleep_threshold: int = 60,
) -> TelegramClient:
    if session is None:
        session = StringSession(settings.session_string) if settings.session_string else settings.session_name
    return TelegramClient(
        session,
        settings.api_id,
        settings.api_hash,
        connection_retries=5,
        retry_delay=1,
        request_retries=5,
        auto_reconnect=True,
        # Short floods are slept through by Telethon; longer ones surface.
        flood_sleep_threshold=flood_sleep_threshold,
        receive_updates=receive_updates,
        # Messages sent while the bot was down are answered after it restarts.
        catch_up=receive_updates,
    )
