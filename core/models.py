"""Tortoise ORM models representing core storage entities."""

from __future__ import annotations

from typing import Optional

from tortoise import fields
from tortoise.models import Model


class User(Model):
    """Represents a Telegram user interacting with the bot.
    
    Attributes:
        id: Primary key.
        userid: Telegram user ID (indexed and unique for fast lookups).
        phone_number: Optional phone number.
        created_at: Account creation timestamp.
        is_superuser: Superuser flag.
        is_staff: Staff member flag.
        files: Reverse relation to user's uploaded files.
    """

    id: int = fields.IntField(pk=True)
    userid: int = fields.BigIntField(index=True, unique=True)
    phone_number: Optional[str] = fields.CharField(max_length=32, null=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)  # Added index for sorting
    last_activity_at = fields.DatetimeField(null=True)
    is_superuser: bool = fields.BooleanField(default=False, index=True)  # Index for admin queries
    is_staff: bool = fields.BooleanField(default=False, index=True)  # Index for admin queries

    files: fields.ReverseRelation["File"]

    class Meta:
        """Model metadata."""

        table = "user"
        indexes = [
            # Composite index for admin queries
            ("is_superuser", "is_staff"),
        ]


class Channel(Model):
    """Represents a channel that users must join before using the bot.
    
    Attributes:
        id: Primary key.
        channel_id: Telegram channel ID or username (indexed for fast lookups).
        channel_link: Channel invitation link.
        created_at: Channel addition timestamp.
        is_active: Whether the channel is active for forced join.
    """

    id: int = fields.IntField(pk=True)
    channel_id: str = fields.CharField(max_length=255, unique=True, index=True)
    channel_link: str = fields.CharField(max_length=255, index=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    is_active: bool = fields.BooleanField(default=True, index=True)

    class Meta:
        """Model metadata."""

        table = "channel"


class File(Model):
    """Represents a stored Telegram media resource.
    
    Supports both single files and album (grouped media).
    Uses Telegram's file_id and access_hash for efficient file sending without re-download.
    
    Attributes:
        id: Primary key.
        type: File type (photo, video, document, etc.).
        size: File size in bytes.
        code: Unique file code for sharing (indexed for fast lookups).
        file_id: Telegram file ID for direct access.
        access_hash: Telegram access hash for file retrieval.
        file_reference: Telegram file reference (bytes) for up-to-date access.
        message_id: Message ID in storage channel (for backup/viewing only).
        count: Download count.
        password: Optional password protection.
        caption: Optional custom caption.
        album_id: Optional album ID for grouped media (same for all files in album).
        album_order: Order of this file within its album (0-based).
        created_at: Upload timestamp (indexed for sorting).
        owner: Foreign key to User model.
    """

    id: int = fields.IntField(pk=True)
    type: str = fields.CharField(max_length=64, index=True)  # Index for filtering by type
    size: int = fields.BigIntField()
    code: str = fields.CharField(max_length=32, unique=True, index=True)
    file_id: int = fields.BigIntField()  # Telegram file ID
    access_hash: int = fields.BigIntField()  # Telegram access hash
    file_reference: bytes = fields.BinaryField()  # Telegram file reference
    message_id: int = fields.BigIntField()  # Message ID in storage channel (backup only)
    count: int = fields.IntField(default=0, index=True)  # Index for popular files queries
    password: Optional[str] = fields.CharField(max_length=255, null=True)
    caption: Optional[str] = fields.TextField(null=True)
    album_id: Optional[str] = fields.CharField(max_length=64, null=True, index=True)  # Group media
    album_order: int = fields.IntField(default=0)  # Order within album
    created_at = fields.DatetimeField(auto_now_add=True, index=True)  # Index for sorting
    expires_at = fields.DatetimeField(null=True)
    max_downloads: Optional[int] = fields.IntField(null=True)

    owner: fields.ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",  # Tortoise ORM app.Model format (app name is "models")
        related_name="files",
        to_field="userid",
        db_column="owner_id",
        on_delete=fields.CASCADE,  # Cascade delete when user is deleted
    )

    class Meta:
        """Model metadata."""

        table = "file"
        indexes = [
            # Composite indexes for common queries
            ("owner_id", "created_at"),  # User's files sorted by date
            ("type", "created_at"),  # Files by type and date
            ("album_id", "album_order"),  # Album files in order
        ]


class FileAccessLog(Model):
    """A successful view of a shared file link by a Telegram user."""

    id: int = fields.IntField(pk=True)
    viewer_id: int = fields.BigIntField(index=True)
    file_code: str = fields.CharField(max_length=32, index=True)
    owner_id: int = fields.BigIntField(index=True)
    accessed_at = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = "file_access_log"
        indexes = [
            ("viewer_id", "accessed_at"),
            ("viewer_id", "file_code"),
            ("file_code", "accessed_at"),
        ]


class BotSettings(Model):
    """Singleton row storing bot-wide configuration toggles.

    Attributes:
        id: Primary key (a single row with id=1 is used).
        global_caption: Caption prepended to every outgoing file, regardless
            of whether the file also has its own caption.
        show_file_captions: When False, only ``global_caption`` is shown and
            each file's own caption is hidden.
    """

    id: int = fields.IntField(pk=True)
    global_caption: Optional[str] = fields.TextField(null=True)
    show_file_captions: bool = fields.BooleanField(default=True)

    class Meta:
        """Model metadata."""

        table = "bot_settings"


class BroadcastJob(Model):
    """Stores outcomes of completed and scheduled admin broadcasts."""

    id: int = fields.IntField(pk=True)
    admin_id: int = fields.BigIntField(index=True)
    delivery_type: str = fields.CharField(max_length=16)
    audience: str = fields.CharField(max_length=128)
    status: str = fields.CharField(max_length=16, default="scheduled", index=True)
    total_count: int = fields.IntField(default=0)
    success_count: int = fields.IntField(default=0)
    failed_count: int = fields.IntField(default=0)
    scheduled_at = fields.DatetimeField(null=True, index=True)
    started_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "broadcast_job"
        indexes = [
            ("status", "scheduled_at"),
            ("admin_id", "started_at"),
        ]
