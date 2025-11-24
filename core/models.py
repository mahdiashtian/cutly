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
