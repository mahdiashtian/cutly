"""Telethon entrypoint for the Cutly file storage bot."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from functools import wraps
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import uvloop
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from decouple import config
from telethon import TelegramClient, events, types
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    UserNotParticipantError,
)
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message as TelethonMessage
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeAudio,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)
from telethon.utils import pack_bot_file_id

from core.database import close_db, init_db
from core.models import File
from core.state import State
from core.upload_session import get_upload_manager
from services import (
    change_admin_from_db,
    create_backup,
    create_channel_from_db,
    create_file_from_db,
    create_user_from_db,
    delete_channel_from_db,
    delete_file_from_db,
    read_channels_from_db,
    read_file_from_db,
    read_files_from_db,
    read_user_from_db,
    read_users,
    userid_list,
)
from utils.filters import admin_filter, compose_filters, conversation, private_only
from utils.helpers import broadcast_to_users, generate_random_text, send_file
from utils.keyboard import (
    ADMIN_KEYBOARD,
    BACK_KEYBOARD,
    JOIN_KEYBOARD,
    START_KEYBOARD,
    UPLOAD_SESSION_KEYBOARD,
    channel_join_btn,
)
from utils.text import (
    account_text,
    admin_panel_text,
    channel_add_text,
    channel_list_text,
    delete_file_text,
    file_saved_in_session_text,
    get_file_text,
    join_panel_text,
    need_join_text,
    start_text,
    tracing_file_text,
    upload_cancelled_text,
    upload_session_summary_text,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)

ADMIN_MASTER = int(config("ADMIN_MASTER", default="1017215648"))
API_ID = int(config("API_ID"))
API_HASH = config("API_HASH")
BOT_TOKEN = config("BOT_TOKEN")
SESSION_STRING = config("SESSION_STRING", default="")
STORAGE_CHANNEL_ID = int(config("STORAGE_CHANNEL_ID", default="0"))
SESSION_NAME = config("SESSION_NAME", default="cutly")
WORKERS = int(config("WORKERS", default="20"))

if SESSION_STRING:
    CLIENT = TelegramClient(
        StringSession(SESSION_STRING),
        API_ID,
        API_HASH,
        connection_retries=5,
        auto_reconnect=True,
        timeout=30,
        request_retries=3,
        flood_sleep_threshold=60,
    )
else:
    CLIENT = TelegramClient(
        SESSION_NAME,
        API_ID,
        API_HASH,
        connection_retries=5,
        auto_reconnect=True,
        timeout=30,
        request_retries=3,
        flood_sleep_threshold=60,
    )

CLIENT.parse_mode = "md"

Handler = Callable[[events.NewMessage.Event], Awaitable[None]]

CONVERSATION_STATE: Dict[int, Optional[State]] = {}
CONVERSATION_OBJECT: Dict[int, Optional[File]] = {}
LIST_VIDEO: List[Dict[str, int]] = []
USER_LIST: List[int] = []
CHANNEL_JOIN_LIST: Optional[Dict[str, Dict[str, str]]] = None
BOT_USERNAME: str = ""
SCHEDULER = AsyncIOScheduler()
ADMIN_PREDICATE = admin_filter(ADMIN_MASTER)
BROADCAST_IN_PROGRESS = False
USER_COMMANDS = {
    "/start",
    "🗳 آپلود فایل",
    "🗑 حذف فایل",
    "📝 تنظیم کپشن",
    "🗞 حذف کپشن",
    "🔐 تنظیم پسورد",
    "🗝 حذف پسورد",
    "🗂 شناسه پیگیری فایل",
    "📂 تاریخچه اپلود",
    "🎫 حساب کاربری",
    "🛠 سازنده",
    "🔙 بازگشت",
    "/admin",
    "🎯 عضویت اجباری",
    "📭 فوروارد همگانی",
    "📬 پیام همگانی",
    "❌ حذف ادمین",
    "👥 نمایش لیست ادمین ها",
    "👤 افزودن ادمین",
    "📈آمار",
    "🔌بک آپ",
    "🔸 لیست کانال ها",
    "▫️ اضافه کردن کانال",
    "▪️ حذف کانال",
}
ADMIN_CONTEXT_STATES = {
    State.USER_ADMIN_PANEL,
    State.USER_SET_ADMIN,
    State.USER_UNSET_ADMIN,
    State.USER_FORWARD_MESSAGE_FOR_ALL,
    State.USER_SEND_MESSAGE_FOR_ALL,
    State.USER_JOIN_CHANNEL_PANEL,
    State.USER_ADD_CHANNEL,
    State.USER_REMOVE_CHANNEL,
}
def is_user_command(text: Optional[str]) -> bool:
    """Return True when the incoming text matches any command/keyboard label."""

    return bool(text and (text.startswith("/") or text in USER_COMMANDS))


def is_valid_code(code: str, max_length: int = 32) -> bool:
    """Validate file code length.
    
    Args:
        code: File code to validate.
        max_length: Maximum allowed length (default: 32 chars).
        
    Returns:
        True if code length is valid, False otherwise.
    """
    return 0 < len(code) <= max_length


def get_display_name(user: Optional[types.User]) -> str:
    """Return a human readable name for a Telegram user."""

    if not user:
        return "کاربر"
    # Check if it's a User object (not Channel)
    if isinstance(user, types.User):
        return user.first_name or user.username or "کاربر"
    return "کاربر"


def format_file_size(size_bytes: int) -> str:
    """Return human readable size string."""

    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    return f"{size_bytes / (1024 ** 3):.1f} GB"


def set_state(user_id: int, state: Optional[State]) -> None:
    """Persist the current conversation state."""

    CONVERSATION_STATE[user_id] = state


def reset_context(user_id: int) -> None:
    """Clear cached conversation context for a user."""

    CONVERSATION_OBJECT[user_id] = None
    set_state(user_id, None)


async def send_user_menu(client: TelegramClient, user_id: int, first_name: str) -> None:
    """Display the default user keyboard and greeting."""

    await client.send_message(
        user_id,
        start_text.format(first_name),
        buttons=START_KEYBOARD,
    )


async def send_admin_menu(client: TelegramClient, user_id: int, first_name: str) -> None:
    """Display the admin control panel keyboard."""

    await client.send_message(
        user_id,
        admin_panel_text.format(first_name),
        buttons=ADMIN_KEYBOARD,
    )


async def send_join_menu(client: TelegramClient, user_id: int, first_name: str) -> None:
    """Display the channel management keyboard."""

    await client.send_message(
        user_id,
        join_panel_text.format(first_name),
        buttons=JOIN_KEYBOARD,
    )


async def build_channel_join_list(client: TelegramClient) -> Dict[str, Dict[str, str]]:
    """Build a cache of mandatory join channels with Redis caching.
    
    Checks Redis cache first for fast access. Falls back to building from
    database if cache miss, then updates cache for next time.
    """
    from core.cache import get_cache
    
    cache = get_cache()
    
    # Try Redis cache first
    cached_channels = await cache.get_channel_list()
    if cached_channels is not None:
        LOGGER.debug(f"✅ Channel list loaded from Redis cache ({len(cached_channels)} channels)")
        return cached_channels
    
    # Cache miss - build from database
    LOGGER.info("⚠️ Channel cache miss, loading from database...")
    payload: Dict[str, Dict[str, str]] = {}
    channels = await read_channels_from_db()
    
    async def fetch_channel_info(channel) -> Tuple[str, str, str]:
        """Fetch channel title or return channel_id as fallback."""
        title = channel.channel_id
        try:
            # Convert channel_id to proper format
            channel_id = channel.channel_id
            if channel_id.startswith('-'):
                entity_id = int(channel_id)
            else:
                entity_id = channel_id
            
            # Use get_entity which uses Telethon's internal cache
            entity = await client.get_entity(entity_id)
            if getattr(entity, "title", None):
                title = entity.title  # type: ignore[assignment]
        except (ValueError, ChannelInvalidError, ChannelPrivateError) as exc:
            LOGGER.warning("Unable to resolve channel %s: %s", channel.channel_id, exc)
        return channel.channel_id, title, channel.channel_link
    
    # Fetch all channel info concurrently with Telethon's built-in caching
    results = await asyncio.gather(
        *[fetch_channel_info(ch) for ch in channels],
        return_exceptions=True,
    )
    
    for result in results:
        if isinstance(result, Exception):
            continue
        channel_id, title, link = result
        payload[channel_id] = {"title": title, "link": link}
    
    # Update Redis cache for next time
    cache_updated = await cache.set_channel_list(payload)
    if cache_updated:
        LOGGER.info(f"✅ Channel list cached in Redis ({len(payload)} channels)")
    
    return payload


async def refresh_channel_join_cache(client: TelegramClient) -> None:
    """Force refresh the join cache after mutations."""
    
    LOGGER.info("🔄 Refreshing channel join cache...")

    global CHANNEL_JOIN_LIST
    CHANNEL_JOIN_LIST = await build_channel_join_list(client)
    
    LOGGER.info(f"✅ Channel join cache refreshed ({len(CHANNEL_JOIN_LIST)} channels)")


async def ensure_channel_join_list(client: TelegramClient) -> Dict[str, Dict[str, str]]:
    """Return a cached join list and hydrate it on first access."""

    global CHANNEL_JOIN_LIST
    if CHANNEL_JOIN_LIST is None:
        CHANNEL_JOIN_LIST = await build_channel_join_list(client)
    return CHANNEL_JOIN_LIST


async def ensure_user_record(user_id: int) -> None:
    """Persist the user in the database if they are new.
    
    Always checks database to ensure user exists, even if in memory list.
    This is important after database recreation.
    """
    
    # Check if user exists in database (more reliable than memory list)
    from core.models import User
    user_exists = await User.filter(userid=user_id).exists()
    
    if not user_exists:
        # Create user in database
        await create_user_from_db({"userid": user_id})
        LOGGER.info(f"✅ User {user_id} created in database")
        
        # Add to memory list if not there
        if user_id not in USER_LIST:
            USER_LIST.append(user_id)
    elif user_id not in USER_LIST:
        # User exists in DB but not in memory list - add to list
        USER_LIST.append(user_id)


async def enforce_channel_membership(event: events.NewMessage.Event) -> bool:
    """Validate that the sender joined every required channel in parallel."""

    channels = await ensure_channel_join_list(event.client)
    if not channels:
        return True
    
    async def check_membership(channel_id: str, data: Dict[str, str]) -> Optional[Dict[str, str]]:
        """Check if user is member or admin of channel, return data if not."""
        try:
            # Convert channel_id to proper entity
            # If it starts with -, it's a numeric ID (convert to int)
            # If it starts with @, it's a username
            if channel_id.startswith('-'):
                entity = int(channel_id)
            else:
                entity = channel_id
            
            # Get user permissions in the channel
            # This will raise UserNotParticipantError if not a member
            permissions = await event.client.get_permissions(entity, event.sender_id)
            
            # If we got permissions, user is a member (or admin/creator)
            return None
                
        except UserNotParticipantError:
            # User is definitely not a member
            LOGGER.info(f"User {event.sender_id} is not a member of {channel_id}")
            return data
        except Exception as e:
            # Any other error, log it and treat as not a member to be safe
            LOGGER.error(f"Error checking membership for {channel_id}: {e}")
            return data
    
    # Check all channels concurrently
    results = await asyncio.gather(
        *[check_membership(ch_id, data) for ch_id, data in channels.items()],
        return_exceptions=True,
    )
    
    missing = [r for r in results if r is not None and not isinstance(r, Exception)]
    
    if not missing:
        return True
    
    buttons = [[channel_join_btn(item["title"], item["link"])] for item in missing]
    token = (event.raw_text or "").split(" ")[-1] if event.raw_text else ""
    start_param = token if token.startswith("get_") else ""
    join_url = f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else "https://t.me"
    if start_param and BOT_USERNAME:
        join_url = f"{join_url}?start={start_param}"
    buttons.append([channel_join_btn("✅ عضو شدم", join_url)])
    await event.client.send_message(
        event.sender_id,
        need_join_text,
        buttons=buttons,
    )
    return False


async def ensure_access(
    event: events.NewMessage.Event,
    *,
    require_join: bool = True,
) -> bool:
    """Ensure the sender exists in DB and joined required channels."""

    await ensure_user_record(event.sender_id)
    if not require_join:
        return True
    return await enforce_channel_membership(event)


async def cleanup_messages(client: TelegramClient) -> None:
    """Delete temporary media previews after the cooldown in parallel."""

    if not LIST_VIDEO:
        return
    pending = LIST_VIDEO.copy()
    LIST_VIDEO.clear()
    
    async def delete_single(record: Dict[str, int]) -> None:
        try:
            await client.delete_messages(record["chat_id"], record["message_id"])
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Unable to delete message %s: %s", record, exc)
    
    # Delete all messages concurrently
    await asyncio.gather(*[delete_single(record) for record in pending], return_exceptions=True)


def parse_channel_payload(text: str) -> Tuple[str, str]:
    """Normalize incoming channel definitions.

    Args:
        text: Raw admin input.

    Returns:
        Tuple ``(channel_id, channel_link)``.

    Raises:
        ValueError: If the provided payload cannot be parsed.
    """

    match = re.search(r"@([^\s]+)", text)
    if match:
        identifier = match.group(1)
        return identifier, f"https://t.me/{identifier}"
    parts = text.split()
    if len(parts) != 2:
        raise ValueError("channel payload must contain link and identifier")
    channel_link, channel_id = parts
    return channel_id, channel_link


def detect_media_payload(message: TelethonMessage) -> Tuple[str, int, int, int, bytes]:
    """Extract normalized media metadata from a Telegram message.

    Args:
        message: Incoming Telegram message.

    Returns:
        Tuple ``(media_type, size, file_id, access_hash, file_reference)`` for efficient file retrieval.

    Raises:
        ValueError: If the message does not contain a supported media type.
    """

    if not message.media or isinstance(message.media, types.MessageMediaWebPage):  # type: ignore[attr-defined]
        raise ValueError("unsupported message type")
    
    media_type = "document"
    size = 0
    file_id = 0
    access_hash = 0
    file_reference = b""
    
    if isinstance(message.media, MessageMediaPhoto):
        media_type = "photo"
        # For photos, get size from largest photo size
        if message.photo and hasattr(message.photo, 'sizes'):
            for photo_size in message.photo.sizes:
                if hasattr(photo_size, 'size'):
                    size = max(size, photo_size.size)
        # Extract file identifiers
        file_id = message.photo.id
        access_hash = message.photo.access_hash
        file_reference = message.photo.file_reference
        
    elif isinstance(message.media, MessageMediaDocument):
        attributes = message.document.attributes or []
        if any(isinstance(attr, DocumentAttributeSticker) for attr in attributes):
            media_type = "sticker"
        elif any(isinstance(attr, DocumentAttributeAnimated) for attr in attributes):
            media_type = "animation"
        elif any(isinstance(attr, DocumentAttributeVideo) for attr in attributes):
            media_type = "video"
        elif any(isinstance(attr, DocumentAttributeAudio) for attr in attributes):
            attr_audio = next(
                attr for attr in attributes if isinstance(attr, DocumentAttributeAudio)
            )
            media_type = "voice" if attr_audio.voice else "audio"
        
        size = message.document.size if hasattr(message.document, 'size') else 0
        # Extract file identifiers
        file_id = message.document.id
        access_hash = message.document.access_hash
        file_reference = message.document.file_reference
    else:
        raise ValueError("unsupported message type")
    
    return media_type, size, file_id, access_hash, file_reference


@CLIENT.on(events.NewMessage(pattern=r"^/start$", func=private_only()))
async def handle_start(event: events.NewMessage.Event) -> None:
    """Handle /start command."""

    if not await ensure_access(event):
        raise events.StopPropagation
    reset_context(event.sender_id)
    sender = await event.get_sender()
    await send_user_menu(event.client, event.sender_id, get_display_name(sender))
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^/start get_(?P<code>[A-Za-z0-9]+)$", func=private_only()))
async def handle_get_file(event: events.NewMessage.Event) -> None:
    """Deliver stored files by code."""

    if not await ensure_access(event):
        raise events.StopPropagation
    reset_context(event.sender_id)
    code = event.pattern_match.group("code")
    file = await read_file_from_db(code)
    if not file:
        await event.client.send_message(event.sender_id, "❌ فایل یافت نشد !")
        sender = await event.get_sender()
        await send_user_menu(event.client, event.sender_id, get_display_name(sender))
        raise events.StopPropagation
    if not file.password or file.owner_id == event.sender_id:
        messages = await send_file(
            event.client,
            event.chat_id,
            file,
            bot_username=BOT_USERNAME,
            keyboard=START_KEYBOARD,
            storage_channel_id=STORAGE_CHANNEL_ID,
        )
        # Add all sent messages to cleanup list
        for message in messages:
            if message:
                LIST_VIDEO.append({"chat_id": message.chat_id, "message_id": message.id})
        return
    CONVERSATION_OBJECT[event.sender_id] = file
    set_state(event.sender_id, State.USER_SEND_PASSWORD_FOR_GET_FILE)
    await event.client.send_message(
        event.sender_id,
        "🔑 لطفا پسورد فایل را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^/admin$", func=compose_filters(private_only(), ADMIN_PREDICATE)))
async def handle_admin_panel(event: events.NewMessage.Event) -> None:
    """Open the admin panel."""

    set_state(event.sender_id, State.USER_ADMIN_PANEL)
    sender = await event.get_sender()
    await send_admin_menu(event.client, event.sender_id, get_display_name(sender))
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        pattern=r"^🔸 لیست کانال ها$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_JOIN_CHANNEL_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_channel_list(event: events.NewMessage.Event) -> None:
    """List required channels."""

    text = "📃 لیست کانال های عضویت اجباری شما :\n"
    channels = await read_channels_from_db()
    if channels:
        for channel in channels:
            text += channel_list_text.format(channel.channel_link, channel.channel_id)
    else:
        text = "❌ هیچ کانالی یافت نشد !"
    await event.client.send_message(event.sender_id, text, buttons=JOIN_KEYBOARD)


@CLIENT.on(
    events.NewMessage(
        pattern=r"^▫️ اضافه کردن کانال$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_JOIN_CHANNEL_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_add_channel_prompt(event: events.NewMessage.Event) -> None:
    """Prompt admin to add a channel."""

    set_state(event.sender_id, State.USER_ADD_CHANNEL)
    await event.client.send_message(
        event.sender_id,
        channel_add_text,
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        pattern=r"^▪️ حذف کانال$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_JOIN_CHANNEL_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_remove_channel_prompt(event: events.NewMessage.Event) -> None:
    """Prompt admin to remove a channel."""

    set_state(event.sender_id, State.USER_REMOVE_CHANNEL)
    await event.client.send_message(
        event.sender_id,
        "🔗 لطفا آیدی عددی کانال را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        pattern=r"^🎯 عضویت اجباری$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_join_panel(event: events.NewMessage.Event) -> None:
    """Show the join management panel."""

    set_state(event.sender_id, State.USER_JOIN_CHANNEL_PANEL)
    sender = await event.get_sender()
    await send_join_menu(event.client, event.sender_id, get_display_name(sender))
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        pattern=r"^👤 افزودن ادمین$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_set_admin_prompt(event: events.NewMessage.Event) -> None:
    """Prompt for admin creation."""

    set_state(event.sender_id, State.USER_SET_ADMIN)
    await event.client.send_message(
        event.sender_id,
        "👤 لطفا آیدی عددی ادمین جدید را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        pattern=r"^❌ حذف ادمین$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_unset_admin_prompt(event: events.NewMessage.Event) -> None:
    """Prompt for admin removal."""

    set_state(event.sender_id, State.USER_UNSET_ADMIN)
    await event.client.send_message(
        event.sender_id,
        "👤 لطفا آیدی عددی ادمین را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        pattern=r"^👥 نمایش لیست ادمین ها$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_admin_list(event: events.NewMessage.Event) -> None:
    """Display all privileged users fetched concurrently."""

    users = await read_users(is_admin=True)
    
    async def get_user_info(user) -> str:
        """Fetch user entity and format info."""
        try:
            entity = await event.client.get_entity(user.userid)
            return f"👤 {get_display_name(entity)} \n🆔 {user.userid} \n\n"
        except ValueError:
            return f"👤 --- \n🆔 {user.userid} \n\n"
    
    # Fetch all user info concurrently
    user_infos = await asyncio.gather(
        *[get_user_info(user) for user in users],
        return_exceptions=True,
    )
    
    text = "👥 لیست ادمین ها : \n\n"
    for info in user_infos:
        if not isinstance(info, Exception):
            text += info
    
    await event.client.send_message(event.sender_id, text, buttons=ADMIN_KEYBOARD)


@CLIENT.on(
    events.NewMessage(
        pattern=r"^🔌بک آپ$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_backup(event: events.NewMessage.Event) -> None:
    """Create and send a PostgreSQL dump."""

    file_path = await create_backup()
    if file_path:
        await event.client.send_file(
            event.sender_id,
            file=file_path,
            caption="📤 بک آپ ربات شما ...",
            buttons=ADMIN_KEYBOARD,
        )
    else:
        await event.client.send_message(
            event.sender_id,
            "❌ مشکلی در ایجاد بک آپ رخ داده است !",
            buttons=ADMIN_KEYBOARD,
        )


@CLIENT.on(
    events.NewMessage(
        pattern=r"^📈آمار$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_status(event: events.NewMessage.Event) -> None:
    """Display usage statistics."""

    users = await read_users()
    files = await read_files_from_db()
    text = (
        "📊 آمار ربات : \n\n"
        f"👥 تعداد کاربران : {len(users)} \n"
        f"📤 تعداد فایل های آپلود شده : {len(files)}"
    )
    await event.client.send_message(event.sender_id, text, buttons=ADMIN_KEYBOARD)


@CLIENT.on(
    events.NewMessage(
        pattern=r"^📭 فوروارد همگانی$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_forward_prompt(event: events.NewMessage.Event) -> None:
    """Ask admin for a broadcast message."""

    set_state(event.sender_id, State.USER_FORWARD_MESSAGE_FOR_ALL)
    await event.client.send_message(
        event.sender_id,
        "📭 لطفا پیام خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        pattern=r"^📬 پیام همگانی$",
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        ),
    )
)
async def handle_broadcast_prompt(event: events.NewMessage.Event) -> None:
    """Ask admin for a broadcast message."""

    set_state(event.sender_id, State.USER_SEND_MESSAGE_FOR_ALL)
    await event.client.send_message(
        event.sender_id,
        "📬 لطفا پیام خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^🔙 بازگشت$", func=private_only()))
async def handle_back(event: events.NewMessage.Event) -> None:
    """Handle the universal back button."""

    if not await ensure_access(event):
        raise events.StopPropagation
    current_state = CONVERSATION_STATE.get(event.sender_id)
    sender = await event.get_sender()
    if current_state in (State.USER_ADD_CHANNEL, State.USER_REMOVE_CHANNEL):
        set_state(event.sender_id, State.USER_JOIN_CHANNEL_PANEL)
        await send_join_menu(event.client, event.sender_id, get_display_name(sender))
    elif current_state in ADMIN_CONTEXT_STATES:
        set_state(event.sender_id, State.USER_ADMIN_PANEL)
        await send_admin_menu(event.client, event.sender_id, get_display_name(sender))
    else:
        reset_context(event.sender_id)
        await send_user_menu(event.client, event.sender_id, get_display_name(sender))
    raise events.StopPropagation
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^🗳 آپلود فایل$", func=private_only()))
async def handle_upload_prompt(event: events.NewMessage.Event) -> None:
    """Start a new upload session."""

    if not await ensure_access(event):
        raise events.StopPropagation
    
    # Start new upload session
    upload_manager = get_upload_manager()
    upload_manager.start_session(event.sender_id)
    
    set_state(event.sender_id, State.USER_UPLOAD_FILE)
    await event.client.send_message(
        event.sender_id,
        "📤 فایل‌های خود را ارسال کنید (تکی یا گروهی)...\n\n"
        "💡 می‌توانید چندین فایل پشت سر هم بفرستید\n"
        "✅ بعد از ارسال همه فایل‌ها، دکمه 'اتمام ارسال' را بزنید",
        buttons=UPLOAD_SESSION_KEYBOARD,
    )
    raise events.StopPropagation
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^🗑 حذف فایل$", func=private_only()))
async def handle_remove_prompt(event: events.NewMessage.Event) -> None:
    """Prompt user for a file code to delete."""

    if not await ensure_access(event):
        raise events.StopPropagation
    set_state(event.sender_id, State.USER_DELETE_FILE)
    await event.client.send_message(
        event.sender_id,
        "🗑 لطفا شناسه فایل خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^📝 تنظیم کپشن$", func=private_only()))
async def handle_set_caption_prompt(event: events.NewMessage.Event) -> None:
    """Prompt user for caption configuration."""

    if not await ensure_access(event):
        raise events.StopPropagation
    set_state(event.sender_id, State.USER_SEND_ID_FOR_SET_CAPTION)
    await event.client.send_message(
        event.sender_id,
        "📝 لطفا شناسه فایل خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^🗞 حذف کپشن$", func=private_only()))
async def handle_unset_caption_prompt(event: events.NewMessage.Event) -> None:
    """Prompt user to remove a caption."""

    if not await ensure_access(event):
        raise events.StopPropagation
    set_state(event.sender_id, State.USER_SEND_ID_FOR_UNSET_CAPTION)
    await event.client.send_message(
        event.sender_id,
        "📝 لطفا شناسه فایل خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^🔐 تنظیم پسورد$", func=private_only()))
async def handle_set_password_prompt(event: events.NewMessage.Event) -> None:
    """Prompt user to set a password."""

    if not await ensure_access(event):
        raise events.StopPropagation
    set_state(event.sender_id, State.USER_SEND_ID_FOR_SET_PASSWORD)
    await event.client.send_message(
        event.sender_id,
        "🔑 لطفا شناسه فایل خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^🗝 حذف پسورد$", func=private_only()))
async def handle_unset_password_prompt(event: events.NewMessage.Event) -> None:
    """Prompt user to remove a password."""

    if not await ensure_access(event):
        raise events.StopPropagation
    set_state(event.sender_id, State.USER_SEND_ID_FOR_UNSET_PASSWORD)
    await event.client.send_message(
        event.sender_id,
        "🔑 لطفا شناسه فایل خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^🗂 شناسه پیگیری فایل$", func=private_only()))
async def handle_tracking_prompt(event: events.NewMessage.Event) -> None:
    """Prompt user to request tracking info."""

    if not await ensure_access(event):
        raise events.StopPropagation
    set_state(event.sender_id, State.USER_SEND_ID_FILE_FOR_TRACKING)
    await event.client.send_message(
        event.sender_id,
        "🗂 لطفا شناسه فایل خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^📂 تاریخچه اپلود$", func=private_only()))
async def handle_file_history(event: events.NewMessage.Event) -> None:
    """List historical uploads for the user, grouped by 5 per message."""

    if not await ensure_access(event):
        raise events.StopPropagation
    
    # Get all user files
    all_files = await read_files_from_db(userid=event.sender_id)
    if not all_files:
        await event.client.send_message(event.sender_id, "❌ فایلی یافت نشد !")
        return
    
    # Filter to only main files (first in album or standalone)
    # Skip _part files which are additional items in an album
    main_files = []
    seen_albums = set()
    
    for file in all_files:
        # If it has album_id and we've seen it, skip
        if file.album_id:
            if file.album_id in seen_albums:
                continue
            seen_albums.add(file.album_id)
        
        # Only include if code doesn't contain "_part"
        if "_part" not in file.code:
            main_files.append(file)
    
    if not main_files:
        await event.client.send_message(event.sender_id, "❌ فایلی یافت نشد !")
        return
    
    # Group files into batches of 5
    batch_size = 5
    total_files = len(main_files)
    
    for batch_idx in range(0, total_files, batch_size):
        batch = main_files[batch_idx:batch_idx + batch_size]
        
        # Build message text for this batch
        lines = [
            f"📂 **تاریخچه آپلود** (دسته {(batch_idx // batch_size) + 1})",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        
        for local_idx, file in enumerate(batch):
            display_idx = batch_idx + local_idx + 1
            # Check if this is an album
            if file.album_id:
                album_files = await File.filter(album_id=file.album_id).order_by("album_order")
                album_count = len(album_files)
                type_labels = {
                    "photo": "عکس",
                    "video": "ویدیو",
                    "voice": "صوتی",
                    "audio": "آهنگ",
                    "document": "مدرک",
                }
                types_count: Counter[str] = Counter(type_labels.get(album_file.type, album_file.type) for album_file in album_files)
                type_summary = ", ".join([f"{count} {label}" for label, count in types_count.items()])
                summary_suffix = f" | {type_summary}" if type_summary else ""
                file_type_display = f"📦 آلبوم ({album_count} فایل{summary_suffix})"
                size_display = format_file_size(sum(af.size for af in album_files))
            else:
                # Single file - display type
                type_icons = {
                    "photo": ("📷", "عکس"),
                    "video": ("🎬", "ویدیو"),
                    "voice": ("🎤", "صوتی"),
                    "audio": ("🎧", "آهنگ"),
                    "document": ("📄", "مدرک"),
                }
                icon, label = type_icons.get(file.type, ("📁", file.type))
                file_type_display = f"{icon} {label}"
                size_display = format_file_size(file.size)
            
            # Format date
            date_str = file.created_at.strftime("%Y/%m/%d")
            
            if local_idx > 0:
                lines.append("────────────────────")
            
            lines.extend(
                [
                    f"{display_idx}. شناسه: `{file.code}`",
                    f"• نوع: {file_type_display}",
                    f"• 💾 حجم: {size_display}",
                    f"• 📅 تاریخ: {date_str}",
                    f"• 👁 دانلود: {file.count} بار",
                    f"• 🔗 https://t.me/{BOT_USERNAME}?start=get_{file.code}",
                ]
            )
        
        text = "\n".join(lines).strip()
        
        # Send keyboard only on last batch
        is_last_batch = (batch_idx + batch_size) >= total_files
        keyboard = START_KEYBOARD if is_last_batch else None
        
        await event.client.send_message(
            event.sender_id,
            text,
            buttons=keyboard
        )
        
        # Small delay between batches
        if not is_last_batch:
            await asyncio.sleep(0.3)


@CLIENT.on(events.NewMessage(pattern=r"^🎫 حساب کاربری$", func=private_only()))
async def handle_account(event: events.NewMessage.Event) -> None:
    """Show account summary."""

    if not await ensure_access(event):
        raise events.StopPropagation
    files = await read_files_from_db(userid=event.sender_id)
    sender = await event.get_sender()
    text = account_text.format(
        len(files),
        get_display_name(sender),
        sender.username or "-----",
        BOT_USERNAME,
    )
    await event.client.send_message(event.sender_id, text, buttons=START_KEYBOARD)


@CLIENT.on(events.NewMessage(pattern=r"^🛠 سازنده$", func=private_only()))
async def handle_creator(event: events.NewMessage.Event) -> None:
    """Display creator information."""

    if not await ensure_access(event):
        raise events.StopPropagation
    await event.client.send_message(
        event.sender_id,
        "👤 سازنده ربات : @",
        buttons=START_KEYBOARD,
    )


@CLIENT.on(
    events.NewMessage(
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADD_CHANNEL),
            ADMIN_PREDICATE,
        )
    )
)
async def handle_add_channel(event: events.NewMessage.Event) -> None:
    """Persist a new join channel."""

    if is_user_command(event.raw_text):
        return
    try:
        channel_id, channel_link = parse_channel_payload(event.raw_text or "")
    except ValueError as exc:
        await event.client.send_message(
            event.sender_id,
            f"❌ {exc}",
            buttons=BACK_KEYBOARD,
        )
        return
    await create_channel_from_db({"channel_id": channel_id, "channel_link": channel_link})
    LOGGER.info(f"➕ Channel added: {channel_id} | {channel_link} | by user {event.sender_id}")
    
    set_state(event.sender_id, State.USER_JOIN_CHANNEL_PANEL)
    await refresh_channel_join_cache(event.client)
    
    await event.client.send_message(
        event.sender_id,
        "✅ کانال با موفقیت اضافه شد !",
        buttons=JOIN_KEYBOARD,
    )


@CLIENT.on(
    events.NewMessage(
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_REMOVE_CHANNEL),
            ADMIN_PREDICATE,
        )
    )
)
async def handle_remove_channel(event: events.NewMessage.Event) -> None:
    """Delete an existing channel."""

    if is_user_command(event.raw_text):
        return
    
    channel_identifier = event.raw_text or ""
    removed = await delete_channel_from_db(channel_identifier)
    
    if removed:
        LOGGER.info(f"➖ Channel removed: {channel_identifier} | by user {event.sender_id}")
        
        set_state(event.sender_id, State.USER_JOIN_CHANNEL_PANEL)
        await refresh_channel_join_cache(event.client)
        
        await event.client.send_message(
            event.sender_id,
            "✅ کانال با موفقیت حذف شد !",
            buttons=JOIN_KEYBOARD,
        )
    else:
        LOGGER.warning(f"❌ Channel not found for removal: {channel_identifier} | by user {event.sender_id}")
        
        await event.client.send_message(
            event.sender_id,
            "❌ کانال یافت نشد !",
            buttons=BACK_KEYBOARD,
        )


@CLIENT.on(
    events.NewMessage(
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_FORWARD_MESSAGE_FOR_ALL),
            ADMIN_PREDICATE,
        )
    )
)
async def handle_forward_message(event: events.NewMessage.Event) -> None:
    """Forward admin message to all users with rate limiting."""

    if is_user_command(event.raw_text):
        return

    if event.message.grouped_id:
        await event.client.send_message(
            event.sender_id,
            "❌ ارسال همگانی آلبوم پشتیبانی نمی‌شود؛ لطفاً یک پیام یا فایل تکی بفرستید.",
            buttons=BACK_KEYBOARD,
        )
        raise events.StopPropagation

    global BROADCAST_IN_PROGRESS
    if BROADCAST_IN_PROGRESS:
        await event.client.send_message(
            event.sender_id,
            "⏳ یک ارسال همگانی در حال انجام است. پس از پایان آن دوباره تلاش کنید.",
            buttons=BACK_KEYBOARD,
        )
        raise events.StopPropagation

    BROADCAST_IN_PROGRESS = True
    set_state(event.sender_id, State.USER_ADMIN_PANEL)
    try:
        users = await read_users()
        status_msg = await event.client.send_message(
            event.sender_id,
            f"⏳ در حال فوروارد به {len(users)} کاربر...",
        )

        async def forward_to_user(user_id: int) -> None:
            await event.client.forward_messages(
                user_id,
                messages=event.message,
                from_peer=event.chat_id,
            )

        success, failed = await broadcast_to_users(
            event.client,
            users,
            forward_to_user,
        )

        await event.client.send_message(
            event.sender_id,
            f"✅ فوروارد انجام شد!\n"
            f"📊 موفق: {success}\n"
            f"❌ ناموفق: {failed}",
            reply_to=status_msg.id,
        )
    except Exception:
        LOGGER.exception("Global forward failed to start or finish")
        await event.client.send_message(
            event.sender_id,
            "❌ ارسال همگانی با خطا متوقف شد. لطفاً دوباره تلاش کنید.",
            buttons=ADMIN_KEYBOARD,
        )
    finally:
        BROADCAST_IN_PROGRESS = False

    sender = await event.get_sender()
    await send_admin_menu(event.client, event.sender_id, get_display_name(sender))
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_SEND_MESSAGE_FOR_ALL),
            ADMIN_PREDICATE,
        )
    )
)
async def handle_broadcast_message(event: events.NewMessage.Event) -> None:
    """Send a copy of admin message to all users with rate limiting."""

    if is_user_command(event.raw_text):
        return

    if event.message.grouped_id:
        await event.client.send_message(
            event.sender_id,
            "❌ ارسال همگانی آلبوم پشتیبانی نمی‌شود؛ لطفاً یک پیام یا فایل تکی بفرستید.",
            buttons=BACK_KEYBOARD,
        )
        raise events.StopPropagation

    global BROADCAST_IN_PROGRESS
    if BROADCAST_IN_PROGRESS:
        await event.client.send_message(
            event.sender_id,
            "⏳ یک ارسال همگانی در حال انجام است. پس از پایان آن دوباره تلاش کنید.",
            buttons=BACK_KEYBOARD,
        )
        raise events.StopPropagation

    BROADCAST_IN_PROGRESS = True
    set_state(event.sender_id, State.USER_ADMIN_PANEL)
    try:
        users = await read_users()
        status_msg = await event.client.send_message(
            event.sender_id,
            f"⏳ در حال ارسال به {len(users)} کاربر...",
        )

        async def send_to_user(user_id: int) -> None:
            # Telethon copies media, text entities and inline markup when a
            # Message instance is supplied, unlike manually re-sending media.
            await event.client.send_message(user_id, event.message)

        success, failed = await broadcast_to_users(
            event.client,
            users,
            send_to_user,
        )

        await event.client.send_message(
            event.sender_id,
            f"✅ پیام ارسال شد!\n"
            f"📊 موفق: {success}\n"
            f"❌ ناموفق: {failed}",
            reply_to=status_msg.id,
        )
    except Exception:
        LOGGER.exception("Global message broadcast failed to start or finish")
        await event.client.send_message(
            event.sender_id,
            "❌ ارسال همگانی با خطا متوقف شد. لطفاً دوباره تلاش کنید.",
            buttons=ADMIN_KEYBOARD,
        )
    finally:
        BROADCAST_IN_PROGRESS = False

    sender = await event.get_sender()
    await send_admin_menu(event.client, event.sender_id, get_display_name(sender))
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_SET_ADMIN),
            ADMIN_PREDICATE,
        )
    )
)
async def handle_set_admin(event: events.NewMessage.Event) -> None:
    """Elevate a user to staff."""

    if is_user_command(event.raw_text):
        return
    try:
        userid = int(event.raw_text.strip())
    except (TypeError, ValueError):
        await event.client.send_message(
            event.sender_id,
            "❌ لطفا آیدی عددی معتبر ارسال کنید !",
            buttons=BACK_KEYBOARD,
        )
        return
    updated = await change_admin_from_db(userid, is_staff=True)
    if updated:
        set_state(event.sender_id, State.USER_ADMIN_PANEL)
        await event.client.send_message(
            event.sender_id,
            "✅ ادمین با موفقیت افزوده شد !",
            buttons=ADMIN_KEYBOARD,
        )
    else:
        await event.client.send_message(
            event.sender_id,
            "❌ کاربر یافت نشد !",
            buttons=BACK_KEYBOARD,
        )


@CLIENT.on(
    events.NewMessage(
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_UNSET_ADMIN),
            ADMIN_PREDICATE,
        )
    )
)
async def handle_unset_admin(event: events.NewMessage.Event) -> None:
    """Remove staff privileges."""

    if is_user_command(event.raw_text):
        return
    try:
        userid = int(event.raw_text.strip())
    except (TypeError, ValueError):
        await event.client.send_message(
            event.sender_id,
            "❌ لطفا آیدی عددی معتبر ارسال کنید !",
            buttons=BACK_KEYBOARD,
        )
        return
    updated = await change_admin_from_db(userid, is_staff=False)
    if updated:
        set_state(event.sender_id, State.USER_ADMIN_PANEL)
        await event.client.send_message(
            event.sender_id,
            "✅ ادمین با موفقیت حذف شد !",
            buttons=ADMIN_KEYBOARD,
        )
    else:
        await event.client.send_message(
            event.sender_id,
            "❌ کاربر یافت نشد !",
            buttons=BACK_KEYBOARD,
        )


@CLIENT.on(
    events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_SEND_ID_FILE_FOR_TRACKING)))
)
async def handle_tracking_request(event: events.NewMessage.Event) -> None:
    """Return file tracking details."""

    if not await ensure_access(event, require_join=False):
        return
    if is_user_command(event.raw_text):
        return
    code = (event.raw_text or "").strip()
    if not is_valid_code(code):
        await event.client.send_message(
            event.sender_id,
            "❌ کد فایل نامعتبر است ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    file = await read_file_from_db(code, userid=event.sender_id)
    if not file:
        await event.client.send_message(
            event.sender_id,
            "❌ فایل یافت نشد ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    
    # Build detailed info
    lines = [
        f"🗂 **اطلاعات فایل**\n",
        f"▪️ شناسه: `{code}`\n"
    ]
    
    # Check if this is an album
    if file.album_id:
        album_files = await File.filter(album_id=file.album_id).order_by("album_order")
        album_count = len(album_files)
        total_size = sum(f.size for f in album_files)
        
        # Count types
        types_count = {}
        for f in album_files:
            types_count[f.type] = types_count.get(f.type, 0) + 1
        
        types_display = ", ".join([f"{count} {type}" for type, count in types_count.items()])
        
        lines.append(f"📦 نوع: آلبوم ({album_count} فایل: {types_display})")
        lines.append(f"💾 حجم کل: {total_size} KB")
    else:
        # Single file
        type_icons = {
            "photo": "📷",
            "video": "🎬",
            "voice": "🎤",
            "document": "📄",
        }
        icon = type_icons.get(file.type, "📁")
        lines.append(f"{icon} نوع: {file.type}")
        lines.append(f"💾 حجم: {file.size} KB")
    
    lines.append(f"🗞 کپشن: {file.caption or 'ندارد'}")
    lines.append(f"🔐 رمز: {file.password or 'ندارد'}")
    lines.append(f"👁 دانلود: {file.count} بار")
    lines.append(f"🕓 تاریخ آپلود: {file.created_at.strftime('%Y/%m/%d %H:%M')}\n")
    lines.append(f"📥 لینک اشتراک گذاری:\nhttps://t.me/{BOT_USERNAME}?start=get_{code}")
    
    text = "\n".join(lines)
    
    await event.client.send_message(event.sender_id, text, buttons=START_KEYBOARD)
    reset_context(event.sender_id)
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_SEND_PASSWORD_FOR_GET_FILE)))
)
async def handle_passworded_file(event: events.NewMessage.Event) -> None:
    """Validate password-protected downloads."""

    if is_user_command(event.raw_text):
        return
    file = CONVERSATION_OBJECT.get(event.sender_id)
    if not file:
        reset_context(event.sender_id)
        return
    if file.password == (event.raw_text or ""):
        messages = await send_file(
            event.client,
            event.chat_id,
            file,
            bot_username=BOT_USERNAME,
            keyboard=START_KEYBOARD,
            storage_channel_id=STORAGE_CHANNEL_ID,
        )
        # Add all sent messages to cleanup list
        for message in messages:
            if message:
                LIST_VIDEO.append({"chat_id": message.chat_id, "message_id": message.id})
        reset_context(event.sender_id)
        raise events.StopPropagation
    else:
        await event.client.send_message(
            event.sender_id,
            "❌ پسورد اشتباه است !",
            buttons=BACK_KEYBOARD,
        )


@CLIENT.on(
    events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_SEND_ID_FOR_UNSET_PASSWORD)))
)
async def handle_unset_password(event: events.NewMessage.Event) -> None:
    """Remove password from a file."""

    if is_user_command(event.raw_text):
        return
    code = (event.raw_text or "").strip()
    if not is_valid_code(code):
        await event.client.send_message(
            event.sender_id,
            "❌ کد فایل نامعتبر است ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    file = await read_file_from_db(code, userid=event.sender_id)
    if not file:
        await event.client.send_message(
            event.sender_id,
            "❌ فایل یافت نشد ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    file.password = None
    await file.save()
    await event.client.send_message(
        event.sender_id,
        "✅ پسورد با موفقیت حذف شد !",
        buttons=START_KEYBOARD,
    )
    reset_context(event.sender_id)
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_SEND_ID_FOR_SET_PASSWORD)))
)
async def handle_get_password_object(event: events.NewMessage.Event) -> None:
    """Store file reference for upcoming password update."""

    if is_user_command(event.raw_text):
        return
    code = (event.raw_text or "").strip()
    if not is_valid_code(code):
        await event.client.send_message(
            event.sender_id,
            "❌ کد فایل نامعتبر است ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    file = await read_file_from_db(code, userid=event.sender_id)
    if not file:
        await event.client.send_message(
            event.sender_id,
            "❌ فایل یافت نشد ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    CONVERSATION_OBJECT[event.sender_id] = file
    set_state(event.sender_id, State.USER_SEND_TEXT_FOR_SET_PASSWORD)
    await event.client.send_message(
        event.sender_id,
        "🔑 لطفا پسورد خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_SEND_TEXT_FOR_SET_PASSWORD)))
)
async def handle_set_password(event: events.NewMessage.Event) -> None:
    """Persist a password on the selected file."""

    if is_user_command(event.raw_text):
        return
    file = CONVERSATION_OBJECT.get(event.sender_id)
    if not file:
        reset_context(event.sender_id)
        return
    file.password = event.raw_text or ""
    await file.save()
    await event.client.send_message(
        event.sender_id,
        "✅ پسورد با موفقیت ثبت شد !",
        buttons=START_KEYBOARD,
    )
    reset_context(event.sender_id)
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_SEND_ID_FOR_UNSET_CAPTION)))
)
async def handle_unset_caption(event: events.NewMessage.Event) -> None:
    """Remove a caption from a file."""

    if is_user_command(event.raw_text):
        return
    code = (event.raw_text or "").strip()
    if not is_valid_code(code):
        await event.client.send_message(
            event.sender_id,
            "❌ کد فایل نامعتبر است ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    file = await read_file_from_db(code, userid=event.sender_id)
    if not file:
        await event.client.send_message(
            event.sender_id,
            "❌ فایل یافت نشد ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    file.caption = None
    await file.save()
    await event.client.send_message(
        event.sender_id,
        "✅ کپشن با موفقیت حذف شد !",
        buttons=START_KEYBOARD,
    )
    reset_context(event.sender_id)
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_SEND_ID_FOR_SET_CAPTION)))
)
async def handle_get_caption_object(event: events.NewMessage.Event) -> None:
    """Store reference for caption updates."""

    if is_user_command(event.raw_text):
        return
    code = (event.raw_text or "").strip()
    if not is_valid_code(code):
        await event.client.send_message(
            event.sender_id,
            "❌ کد فایل نامعتبر است ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    file = await read_file_from_db(code, userid=event.sender_id)
    if not file:
        await event.client.send_message(
            event.sender_id,
            "❌ فایل یافت نشد ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    CONVERSATION_OBJECT[event.sender_id] = file
    set_state(event.sender_id, State.USER_SEND_TEXT_FOR_SET_CAPTION)
    await event.client.send_message(
        event.sender_id,
        "📝 لطفا کپشن خود را ارسال کنید ...",
        buttons=BACK_KEYBOARD,
    )
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_SEND_TEXT_FOR_SET_CAPTION)))
)
async def handle_set_caption(event: events.NewMessage.Event) -> None:
    """Persist a caption for the selected file."""

    if is_user_command(event.raw_text):
        return
    file = CONVERSATION_OBJECT.get(event.sender_id)
    if not file:
        reset_context(event.sender_id)
        return
    file.caption = event.raw_text or ""
    await file.save()
    await event.client.send_message(
        event.sender_id,
        "✅ کپشن با موفقیت ثبت شد !",
        buttons=START_KEYBOARD,
    )
    reset_context(event.sender_id)
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_DELETE_FILE))))
async def handle_delete_file(event: events.NewMessage.Event) -> None:
    """Delete a file owned by the user."""

    if is_user_command(event.raw_text):
        return
    code = (event.raw_text or "").strip()
    if not is_valid_code(code):
        await event.client.send_message(
            event.sender_id,
            "❌ کد فایل نامعتبر است ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return
    deleted = await delete_file_from_db(event.sender_id, code)
    if deleted:
        await event.client.send_message(
            event.sender_id,
            delete_file_text,
            buttons=START_KEYBOARD,
        )
        reset_context(event.sender_id)
        raise events.StopPropagation
    else:
        await event.client.send_message(
            event.sender_id,
            "❌ فایل یافت نشد ! لطفا دوباره تلاش کنید:",
            buttons=BACK_KEYBOARD,
        )
        return


@CLIENT.on(events.Album(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_UPLOAD_FILE))))
async def handle_upload_album(event: events.Album.Event) -> None:
    """Handle album upload - store in storage channel and add to session."""

    if not STORAGE_CHANNEL_ID:
        await event.client.send_message(
            event.sender_id,
            "❌ سرور ذخیره‌سازی تنظیم نشده است! لطفاً STORAGE_CHANNEL_ID را در .env تنظیم کنید.",
        )
        return
    
    upload_manager = get_upload_manager()
    session = upload_manager.get_session(event.sender_id)
    
    if not session:
        await event.client.send_message(
            event.sender_id,
            "❌ جلسه آپلود یافت نشد! لطفاً دوباره تلاش کنید.",
        )
        return
    
    # First, validate all files in the album and extract their identifiers
    validated_files = []
    for msg in event.messages:
        try:
            media_type, size, file_id, access_hash, file_reference = detect_media_payload(msg)
            validated_files.append((msg, media_type, size, file_id, access_hash, file_reference))
        except ValueError:
            await event.client.send_message(
                event.sender_id,
                "❌ یکی از فایل‌های گروه شما پشتیبانی نمیشود! لطفاً فقط عکس، ویدیو، صوت یا سند ارسال کنید.",
            )
            return
    
    # If all files are valid, proceed with forwarding
    try:
        # Forward all messages in album to storage channel (for backup/viewing)
        forwarded_messages = await event.client.forward_messages(
            STORAGE_CHANNEL_ID,
            event.messages
        )
        
        # Add each file to session with full metadata
        for (_, media_type, size, file_id, access_hash, file_reference), forwarded_msg in zip(validated_files, forwarded_messages):
            session.add_file(
                message_id=forwarded_msg.id,
                media_type=media_type,
                size=size,
                file_id=file_id,
                access_hash=access_hash,
                file_reference=file_reference
            )
        
        summary = session.get_summary()
        await event.client.send_message(
            event.sender_id,
            file_saved_in_session_text.format(
                summary['total_count'],
                summary['total_size_mb']
            ),
            buttons=UPLOAD_SESSION_KEYBOARD,
        )
        
    except Exception as e:
        LOGGER.error(f"Failed to store album: {e}")
        await event.client.send_message(
            event.sender_id,
            "❌ خطا در ذخیره‌سازی آلبوم! لطفاً دوباره تلاش کنید.",
        )


@CLIENT.on(events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_UPLOAD_FILE))))
async def handle_upload_file(event: events.NewMessage.Event) -> None:
    """Handle single file upload - store in storage channel and add to session."""

    if is_user_command(event.raw_text):
        return
    
    message = event.message
    
    # Skip if this message is part of an album (will be handled by handle_upload_album)
    if message.grouped_id is not None:
        return
    
    # Skip if this is a button text (will be handled by other handlers)
    button_texts = ["✅ اتمام ارسال فایل", "❌ لغو و بازگشت", "🔙 بازگشت"]
    if message.text and message.text in button_texts:
        return
    
    if message.text or message.sticker or not message.media:
        await event.client.send_message(
            event.sender_id,
            "❌ فایل شما پشتیبانی نمیشود !",
        )
        return
    
    # Check if storage channel is configured
    if not STORAGE_CHANNEL_ID:
        await event.client.send_message(
            event.sender_id,
            "❌ سرور ذخیره‌سازی تنظیم نشده است! لطفاً STORAGE_CHANNEL_ID را در .env تنظیم کنید.",
        )
        return
    
    upload_manager = get_upload_manager()
    session = upload_manager.get_session(event.sender_id)
    
    if not session:
        await event.client.send_message(
            event.sender_id,
            "❌ جلسه آپلود یافت نشد! لطفاً دوباره تلاش کنید.",
        )
        return
    
    try:
        media_type, size, file_id, access_hash, file_reference = detect_media_payload(message)
    except ValueError:
        await event.client.send_message(
            event.sender_id,
            "❌ فایل شما پشتیبانی نمیشود !",
        )
        return
    
    try:
        # Forward message to storage channel (for backup/viewing)
        forwarded_msg = await event.client.forward_messages(
            STORAGE_CHANNEL_ID,
            message
        )
        message_id = forwarded_msg.id if not isinstance(forwarded_msg, list) else forwarded_msg[0].id
        
        # Add to session with full metadata
        session.add_file(
            message_id=message_id,
            media_type=media_type,
            size=size,
            file_id=file_id,
            access_hash=access_hash,
            file_reference=file_reference
        )
        
        summary = session.get_summary()
        await event.client.send_message(
            event.sender_id,
            file_saved_in_session_text.format(
                summary['total_count'],
                summary['total_size_mb']
            ),
            buttons=UPLOAD_SESSION_KEYBOARD,
        )
        
    except Exception as e:
        LOGGER.error(f"Failed to store file: {e}")
        await event.client.send_message(
            event.sender_id,
            "❌ خطا در ذخیره‌سازی فایل! لطفاً دوباره تلاش کنید.",
        )


@CLIENT.on(events.NewMessage(pattern=r"^✅ اتمام ارسال فایل$", func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_UPLOAD_FILE))))
async def handle_finish_upload(event: events.NewMessage.Event) -> None:
    """Finish upload session and save all files to database."""

    upload_manager = get_upload_manager()
    session = upload_manager.get_session(event.sender_id)
    
    if not session or not session.files:
        await event.client.send_message(
            event.sender_id,
            "❌ هیچ فایلی برای ذخیره یافت نشد!",
            buttons=START_KEYBOARD,
        )
        reset_context(event.sender_id)
        raise events.StopPropagation
    
    try:
        # Ensure user exists in database (important after DB recreation)
        await ensure_user_record(event.sender_id)
        
        # Generate unique code and album_id for all files
        code = generate_random_text(15)
        album_id = generate_random_text(20) if len(session.files) > 1 else None
        
        LOGGER.info(f"Saving {len(session.files)} files with code={code}, album_id={album_id}")
        
        # Save all files to database with Telegram file identifiers
        for idx, file_data in enumerate(session.files):
            file_dict = {
                "type": file_data.media_type,
                "code": code if idx == 0 else f"{code}_part{idx}",
                "file_id": file_data.file_id,
                "access_hash": file_data.access_hash,
                "file_reference": file_data.file_reference,
                "message_id": file_data.message_id,  # For backup/viewing in storage channel
                "owner_id": event.sender_id,
                "size": file_data.size,
                "album_id": album_id,
                "album_order": idx,
            }
            
            LOGGER.debug(f"File {idx}: type={file_dict['type']}, file_id={file_dict['file_id']}, "
                        f"size={file_dict['size']}, code={file_dict['code']}")
            
            try:
                await create_file_from_db(file_dict)
                LOGGER.info(f"✅ File {idx} saved successfully")
            except Exception as e:
                LOGGER.error(f"❌ Failed to save file {idx}: {e}")
                LOGGER.error(f"File data: {file_dict}")
                raise
        
        # Get summary
        summary = session.get_summary()
        
        # Send summary to user
        await event.client.send_message(
            event.sender_id,
            upload_session_summary_text.format(
                summary['photos'],
                summary['videos'],
                summary['voices'],
                summary['audios'],
                summary['documents'],
                summary['total_size_mb'],
                BOT_USERNAME,
                code
            ),
            buttons=START_KEYBOARD,
        )
        
        # Clear session
        upload_manager.clear_session(event.sender_id)
        reset_context(event.sender_id)
        
    except Exception as e:
        LOGGER.error(f"Failed to finish upload: {e}")
        await event.client.send_message(
            event.sender_id,
            "❌ خطا در ذخیره‌سازی نهایی! لطفاً دوباره تلاش کنید.",
            buttons=START_KEYBOARD,
        )
        upload_manager.clear_session(event.sender_id)
        reset_context(event.sender_id)
    
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(pattern=r"^❌ لغو و بازگشت$", func=compose_filters(private_only(), conversation(CONVERSATION_STATE, State.USER_UPLOAD_FILE))))
async def handle_cancel_upload(event: events.NewMessage.Event) -> None:
    """Cancel upload session and delete all files from storage channel."""

    upload_manager = get_upload_manager()
    session = upload_manager.get_session(event.sender_id)
    
    if not session or not session.files:
        await event.client.send_message(
            event.sender_id,
            "❌ هیچ فایلی برای حذف یافت نشد!",
            buttons=START_KEYBOARD,
        )
        reset_context(event.sender_id)
        raise events.StopPropagation
    
    try:
        file_count = len(session.files)
        
        # Clear session only - files remain in storage channel but won't be saved to DB
        # Since no code was generated yet, there's no DB entry to delete
        LOGGER.info(f"Upload cancelled by user {event.sender_id}, clearing session with {file_count} files")
        
        await event.client.send_message(
            event.sender_id,
            upload_cancelled_text.format(file_count),
            buttons=START_KEYBOARD,
        )
        
        # Clear session
        upload_manager.clear_session(event.sender_id)
        reset_context(event.sender_id)
        
    except Exception as e:
        LOGGER.error(f"Failed to cancel upload: {e}")
        await event.client.send_message(
            event.sender_id,
            "❌ خطا در حذف فایل‌ها! لطفاً دوباره تلاش کنید.",
            buttons=START_KEYBOARD,
        )
        upload_manager.clear_session(event.sender_id)
        reset_context(event.sender_id)
    
    raise events.StopPropagation


@CLIENT.on(events.NewMessage(func=compose_filters(private_only(), conversation(CONVERSATION_STATE, None))))
async def handle_idle(event: events.NewMessage.Event) -> None:
    """Fallback handler for idle state."""

    if not await ensure_access(event):
        raise events.StopPropagation
    if is_user_command(event.raw_text):
        return
    sender = await event.get_sender()
    await send_user_menu(event.client, event.sender_id, get_display_name(sender))
    raise events.StopPropagation


@CLIENT.on(
    events.NewMessage(
        func=compose_filters(
            private_only(),
            conversation(CONVERSATION_STATE, State.USER_ADMIN_PANEL),
            ADMIN_PREDICATE,
        )
    )
)
async def handle_admin_idle(event: events.NewMessage.Event) -> None:
    """Fallback handler for admin state."""

    if not await ensure_access(event):
        raise events.StopPropagation
    # Admin commands already have dedicated handlers; no extra response required.
    return


async def main() -> None:
    """Bootstrap database, client, scheduler, and Redis cache."""
    from core.cache import get_cache

    global USER_LIST, BOT_USERNAME
    
    # Initialize database
    await init_db()
    
    # Initialize Redis cache
    cache = get_cache()
    cache_connected = await cache.connect()
    
    if cache_connected:
        LOGGER.info("🚀 Cache warming started...")
        
        # Warm up user list cache
        user_ids = list(await userid_list())
        USER_LIST = user_ids
        LOGGER.info(f"✅ Cached {len(user_ids)} users")
        
        # Warm up admin list cache
        admin_users = await read_users(is_admin=True)
        admin_ids = [u.userid for u in admin_users]
        await cache.set_admin_list(admin_ids)
        LOGGER.info(f"✅ Cached {len(admin_ids)} admins")
    else:
        # Fallback without cache
        USER_LIST = list(await userid_list())
        LOGGER.warning("⚠️ Running without Redis cache")
    
    # Start Telegram client
    await CLIENT.start(bot_token=BOT_TOKEN)
    me = await CLIENT.get_me()
    BOT_USERNAME = (me.username or "").lstrip("@")
    
    # Warm up channel cache
    LOGGER.info("🔄 Warming up channel cache...")
    await refresh_channel_join_cache(CLIENT)
    
    if cache_connected:
        # Verify channel cache was populated
        cached_channels = await cache.get_channel_list()
        if cached_channels:
            LOGGER.info(f"✅ Cached {len(cached_channels)} channels in Redis")
        else:
            LOGGER.warning("⚠️ No channels found in cache after warming")
        LOGGER.info("🎯 Cache warming completed!")
    
    # Start scheduler
    SCHEDULER.add_job(cleanup_messages, "interval", seconds=30, args=[CLIENT])
    SCHEDULER.start()
    
    try:
        LOGGER.info(f"✅ Bot @{BOT_USERNAME} is running with Redis cache support!")
        await CLIENT.run_until_disconnected()
    finally:
        SCHEDULER.shutdown()
        await cache.close()
        await close_db()
        LOGGER.info("Bot shut down gracefully")


if __name__ == "__main__":
    uvloop.install()
    asyncio.run(main())
