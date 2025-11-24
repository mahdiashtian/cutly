"""Utility helper functions for the bot."""

from __future__ import annotations

import asyncio
import random
import string
from typing import Any, Callable, List, Tuple

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

from core.models import File, User
from utils.keyboard import KeyboardLayout


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
    
    # Check if this file is part of an album
    if file.album_id:
        # Retrieve all files in the album, ordered by album_order
        album_files = await File.filter(album_id=file.album_id).order_by("album_order")
        
        # Prepare InputMedia list for album
        media_list = []
        for album_file in album_files:
            # Create appropriate InputMedia based on type
            if album_file.type == "photo":
                input_file = InputPhoto(
                    id=album_file.file_id,
                    access_hash=album_file.access_hash,
                    file_reference=album_file.file_reference
                )
                media_list.append(input_file)
            else:
                # For video, document, etc.
                input_file = InputDocument(
                    id=album_file.file_id,
                    access_hash=album_file.access_hash,
                    file_reference=album_file.file_reference
                )
                media_list.append(input_file)
        
        if not media_list:
            raise ValueError("No valid media files in album")
        
        # Send as album using send_file with list of InputMedia
        caption = (file.caption or "") + footer
        
        try:
            sent_messages = await client.send_file(
                chat_id,
                file=media_list,  # List of InputPhoto/InputDocument
                caption=caption,
                buttons=keyboard
            )
        except Exception as e:
            # If album sending fails, try one by one
            sent_messages = []
            for idx, (input_file, album_file) in enumerate(zip(media_list, album_files)):
                msg_caption = caption if idx == 0 else None
                msg_keyboard = keyboard if idx == len(media_list) - 1 else None
                
                try:
                    msg = await client.send_file(
                        chat_id,
                        file=input_file,
                        caption=msg_caption,
                        buttons=msg_keyboard
                    )
                    sent_messages.append(msg)
                except Exception as e2:
                    # Log error but continue
                    pass
        
        # Ensure we have a list
        if not isinstance(sent_messages, list):
            sent_messages = [sent_messages]
        
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
        
        caption = (file.caption or "") + footer
        
        # Send the file using InputMedia
        message = await client.send_file(
            chat_id,
            file=input_file,
            caption=caption,
            buttons=keyboard
        )
        
        # Increment count after successful send
        file.count += 1
        await file.save()
        
        return [message]


async def broadcast_to_users(
    client: TelegramClient,
    users: List[User],
    send_callback: Callable[[int], Any],
    *,
    max_concurrent: int = 20,
    delay_between_batches: float = 1.0,
) -> Tuple[int, int]:
    """Broadcast messages to multiple users with rate limiting.

    Args:
        client: Active Telegram client.
        users: List of users to send messages to.
        send_callback: Async function that takes user_id and sends the message.
        max_concurrent: Maximum number of concurrent sends (default: 20).
        delay_between_batches: Delay in seconds between batches (default: 1.0).

    Returns:
        Tuple of (successful_count, failed_count).

    Examples:
        >>> async def send_msg(uid):
        ...     await client.send_message(uid, "Hello")
        >>> success, failed = await broadcast_to_users(client, users, send_msg)
    """

    semaphore = asyncio.Semaphore(max_concurrent)
    success_count = 0
    failed_count = 0

    async def send_with_limit(user: User) -> None:
        nonlocal success_count, failed_count
        async with semaphore:
            try:
                await send_callback(user.userid)
                success_count += 1
            except Exception:  # noqa: BLE001
                failed_count += 1
            # Small delay to avoid hitting rate limits
            await asyncio.sleep(0.05)

    # Process users in batches
    tasks = [send_with_limit(user) for user in users]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    return success_count, failed_count

