"""Utility helper functions for the bot."""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import string
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from telethon.client.telegramclient import TelegramClient
from telethon.tl.custom.message import Message
from telethon.tl.types import (
    InputMediaPhoto,
    InputMediaDocument,
    InputPhoto,
    InputDocument,
    InputFileLocation,
    InputPhotoFileLocation,
    InputDocumentFileLocation,
)
from telethon.utils import resolve_bot_file_id

from core.models import BotSettings, File, User
from services.settings import get_bot_settings
from utils.keyboard import KeyboardLayout
from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    InputUserDeactivatedError,
    PeerIdInvalidError,
    RpcCallFailError,
    ServerError,
    TimedOutError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UserIsBlockedError,
)
from telethon.errors.common import InvalidBufferError

LOGGER = logging.getLogger(__name__)


def build_file_caption(file_caption: Optional[str], settings: BotSettings) -> str:
    """Combine a file's own caption with the admin-configured global caption.

    The global caption always leads. The file's own caption is appended only
    when ``settings.show_file_captions`` is enabled.
    """

    parts = [part for part in (settings.global_caption, file_caption if settings.show_file_captions else None) if part]
    return "\n".join(parts)


def generate_random_text(length: int = 15, existing_text: str = "") -> str:
    """Return a pseudo-random alphanumeric string.

    Args:
        length: Number of characters to generate. Must be positive.
        existing_text: Optional prefix that will be prepended.

    Returns:
        Randomized string value.

    Raises:
        ValueError: If ``length`` is less than ``1``.
        
    Examples:
        >>> code = generate_random_text(15)
        >>> len(code)
        15
    """

    if length < 1:
        raise ValueError("length must be greater than zero")
    characters = string.ascii_letters + string.digits
    random_text = "".join(random.choice(characters) for _ in range(length))
    if existing_text:
        random_text = f"{existing_text}{random_text}"
    return random_text


async def send_file(
    client: TelegramClient,
    chat_id: int,
    file: File,
    *,
    bot_username: str,
    keyboard: KeyboardLayout,
    storage_channel_id: int,
) -> List[Message]:
    """Send a stored media file or album back to the user using Telegram file IDs.

    Uses file_id and access_hash stored in database for efficient sending
    without downloading/re-uploading. Supports both single files and albums.

    Args:
        client: Active Telegram client.
        chat_id: Destination chat identifier.
        file: Stored file metadata with file_id and access_hash.
        bot_username: Username used in the footer caption.
        keyboard: Reply keyboard to attach.
        storage_channel_id: ID of the storage channel (unused, kept for compatibility).

    Returns:
        List of sent Message objects (single item for single file, multiple for album).

    Raises:
        ValueError: If the file cannot be sent.

    Examples:
        >>> messages = await send_file(
        ...     client, chat_id, file,
        ...     bot_username="cutly_bot",
        ...     keyboard=START_KEYBOARD,
        ...     storage_channel_id=-1001234567890
        ... )
    """
    
    footer = (
        f"\n👁 تعداد دانلود : {file.count + 1}\n"
        f"❌ این پیام بعد از ۳۰ ثانیه حذف می شود\n\n@{bot_username}"
    )
    settings = await get_bot_settings()

    # Check if this file is part of an album
    if file.album_id:
        # Retrieve all files in the album, ordered by album_order
        album_files = await File.filter(album_id=file.album_id).order_by("album_order")
        
        # Separate media into groupable (photos/videos) and fallback (audio, document, ...)
        grouped_pairs = []
        fallback_pairs = []
        for album_file in album_files:
            if album_file.type == "photo":
                input_media = InputPhoto(
                    id=album_file.file_id,
                    access_hash=album_file.access_hash,
                    file_reference=album_file.file_reference
                )
                grouped_pairs.append((album_file, input_media))
            elif album_file.type == "video":
                input_media = InputDocument(
                    id=album_file.file_id,
                    access_hash=album_file.access_hash,
                    file_reference=album_file.file_reference
                )
                grouped_pairs.append((album_file, input_media))
            else:
                input_media = InputDocument(
                    id=album_file.file_id,
                    access_hash=album_file.access_hash,
                    file_reference=album_file.file_reference
                )
                fallback_pairs.append((album_file, input_media))
        
        caption = build_file_caption(file.caption, settings) + footer
        caption_used = False
        sent_messages: List[Message] = []
        
        # Send grouped photos/videos together if present
        if grouped_pairs:
            media_list = [media for _, media in grouped_pairs]
            try:
                grouped_result = await client.send_file(
                    chat_id,
                    file=media_list,
                    caption=caption,
                )
                caption_used = True
            except Exception:
                grouped_result = []
                for idx, (album_file, input_media) in enumerate(grouped_pairs):
                    msg_caption = caption if not caption_used else None
                    try:
                        msg = await client.send_file(
                            chat_id,
                            file=input_media,
                            caption=msg_caption,
                        )
                        caption_used = caption_used or msg_caption is not None
                        grouped_result.append(msg)
                    except Exception:
                        continue
            if grouped_result:
                if isinstance(grouped_result, list):
                    sent_messages.extend(grouped_result)
                else:
                    sent_messages.append(grouped_result)
        
        # Send fallback media (audio/voice/documents) individually
        for idx, (album_file, input_media) in enumerate(fallback_pairs):
            msg_caption = caption if not caption_used else None
            msg = await client.send_file(
                chat_id,
                file=input_media,
                caption=msg_caption,
            )
            caption_used = caption_used or msg_caption is not None
            sent_messages.append(msg)
        
        if not grouped_pairs and not fallback_pairs:
            raise ValueError("No valid media files in album")
        
        # Increment count for each file in album
        for album_file in album_files:
            album_file.count += 1
            await album_file.save()
        
        return sent_messages
    
    else:
        # Single file - create appropriate InputMedia
        if file.type == "photo":
            input_file = InputPhoto(
                id=file.file_id,
                access_hash=file.access_hash,
                file_reference=file.file_reference
            )
        else:
            input_file = InputDocument(
                id=file.file_id,
                access_hash=file.access_hash,
                file_reference=file.file_reference
            )
        
        caption = build_file_caption(file.caption, settings) + footer

        # Send the file using InputMedia
        message = await client.send_file(
            chat_id,
            file=input_file,
            caption=caption,
        )
        
        # Increment count after successful send
        file.count += 1
        await file.save()
        
        return [message]


async def broadcast_to_users(
    client: TelegramClient,
    users: List['User'],
    send_callback: Callable[[int], Any],
    *,
    max_concurrent: int = 5,
    batch_size: int = 50,
    delay_between_batches: float = 30.0,
    max_retries: int = 2,
    cancel_event: Optional[asyncio.Event] = None,
    on_delivery: Optional[Callable[[int, bool, Optional[str]], Awaitable[None] | None]] = None,
) -> Tuple[int, int]:
    """Send a message to every user without allowing one failure to stop a broadcast.

    Flood waits are shared by all workers.  Retrying happens *after* a worker
    releases the semaphore, which avoids deadlocking the whole broadcast when
    several deliveries receive a FloodWait at once.
    """
    if max_concurrent < 1:
        raise ValueError("max_concurrent must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")

    semaphore = asyncio.Semaphore(max_concurrent)
    counter_lock = asyncio.Lock()
    flood_lock = asyncio.Lock()
    flood_until = 0.0
    success_count = 0
    failed_count = 0

    async def wait_for_flood_cooldown() -> None:
        """Wait until a FloodWait raised by another worker has elapsed."""
        while True:
            async with flood_lock:
                remaining = flood_until - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            await asyncio.sleep(remaining)

    async def extend_flood_cooldown(seconds: float) -> float:
        """Extend the global cooldown and return the time remaining to wait."""
        nonlocal flood_until
        async with flood_lock:
            now = asyncio.get_running_loop().time()
            flood_until = max(flood_until, now + seconds)
            return max(0.0, flood_until - now)

    async def mark_failed(user: 'User', error: Exception) -> None:
        nonlocal failed_count
        LOGGER.warning("Broadcast to %s failed: %s", user.userid, error)
        async with counter_lock:
            failed_count += 1
        await report_delivery(user.userid, False, str(error))

    async def report_delivery(user_id: int, success: bool, error: Optional[str] = None) -> None:
        if on_delivery is None:
            return
        try:
            result = on_delivery(user_id, success, error)
            if inspect.isawaitable(result):
                await result
        except Exception:
            # Progress/reporting failures must never change delivery results.
            LOGGER.exception("Broadcast delivery reporter failed for %s", user_id)

    async def send_with_limit(user: 'User') -> None:
        nonlocal success_count, failed_count
        for attempt in range(max_retries + 1):
            if cancel_event and cancel_event.is_set():
                return
            await wait_for_flood_cooldown()
            try:
                async with semaphore:
                    # A worker may have set a cooldown while this one was
                    # waiting for a permit, so check once more before sending.
                    await wait_for_flood_cooldown()
                    if cancel_event and cancel_event.is_set():
                        return
                    await send_callback(user.userid)
                async with counter_lock:
                    success_count += 1
                await report_delivery(user.userid, True)
                return
            except FloodWaitError as error:
                wait_time = await extend_flood_cooldown(
                    max(error.seconds, 30) + random.uniform(3, 10)
                )
                LOGGER.warning(
                    "Telegram requested a %.0f-second broadcast cooldown (user %s).",
                    wait_time,
                    user.userid,
                )
            except InvalidBufferError as error:
                if "429" not in str(error):
                    await mark_failed(user, error)
                    return
                wait_time = await extend_flood_cooldown(random.uniform(45, 90))
                LOGGER.warning(
                    "Telegram returned HTTP 429; pausing broadcast for %.0f seconds.",
                    wait_time,
                )
            except (
                UserIsBlockedError,
                PeerIdInvalidError,
                InputUserDeactivatedError,
                UserDeactivatedError,
                UserDeactivatedBanError,
                ChatWriteForbiddenError,
            ) as error:
                await mark_failed(user, error)
                return
            except (asyncio.TimeoutError, OSError, TimedOutError, ServerError, RpcCallFailError) as error:
                if attempt == max_retries:
                    await mark_failed(user, error)
                    return
                retry_delay = min(5 * (attempt + 1), 15) + random.uniform(0.5, 2)
                LOGGER.warning(
                    "Temporary broadcast error for %s; retrying in %.1f seconds: %s",
                    user.userid,
                    retry_delay,
                    error,
                )
                await asyncio.sleep(retry_delay)
                continue
            except Exception as error:
                await mark_failed(user, error)
                return

            if attempt == max_retries:
                await mark_failed(user, error)
                return

            # The cooldown is global, so this sleep lets other tasks observe
            # it too, and (unlike recursive retries) holds no semaphore permit.
            await asyncio.sleep(wait_time)

        # This is only reachable when a retryable error exhausts its retries.
        await mark_failed(user, RuntimeError("broadcast retries exhausted"))

    async def send_and_pace(user: 'User') -> None:
        try:
            await send_with_limit(user)
        finally:
            # Keep a conservative per-delivery pace even after failures.
            await asyncio.sleep(2.0 + random.uniform(0.6, 2.2))

    for i in range(0, len(users), batch_size):
        if cancel_event and cancel_event.is_set():
            break
        batch = users[i : i + batch_size]
        tasks = [send_and_pace(user) for user in batch]
        await asyncio.gather(*tasks, return_exceptions=True)
        if i + batch_size < len(users):
            await asyncio.sleep(delay_between_batches + random.uniform(-10, 15))

    return success_count, failed_count
