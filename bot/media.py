"""Reading Telegram media references out of an incoming message."""
from __future__ import annotations

from dataclasses import dataclass

from telethon.tl.custom import Message
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeAudio,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from core.enums import MediaType
from schemas.link import MediaItem


@dataclass(frozen=True, slots=True)
class MediaRef:
    """Media identity as received; the storage-channel copy is added later."""

    media_type: MediaType
    size: int
    file_id: int
    access_hash: int
    file_reference: bytes

    def stored_as(self, storage_message_id: int) -> MediaItem:
        return MediaItem(
            media_type=self.media_type, size=self.size, tg_file_id=self.file_id,
            tg_access_hash=self.access_hash, tg_file_reference=self.file_reference,
            storage_message_id=storage_message_id,
        )


def extract_media(message: Message) -> MediaRef | None:
    """``None`` for anything that cannot be stored (text, stickers, polls, links…).

    Stickers are rejected as before: Telegram does not show a caption under a
    sticker, so the download counter / auto-delete notice would be lost.
    """
    if isinstance(message.media, MessageMediaPhoto) and message.photo:
        photo = message.photo
        return MediaRef(MediaType.PHOTO, message.file.size or 0, photo.id, photo.access_hash, photo.file_reference)
    if isinstance(message.media, MessageMediaDocument) and message.document:
        document = message.document
        media_type = _document_type(document.attributes or [])
        if media_type is None:
            return None
        return MediaRef(media_type, document.size or 0, document.id, document.access_hash, document.file_reference)
    return None


def _document_type(attributes: list) -> MediaType | None:
    kinds = {type(attribute) for attribute in attributes}
    if DocumentAttributeSticker in kinds:
        return None
    if DocumentAttributeAnimated in kinds:  # GIFs also carry a video attribute
        return MediaType.ANIMATION
    if DocumentAttributeVideo in kinds:
        return MediaType.VIDEO
    audio = next((a for a in attributes if isinstance(a, DocumentAttributeAudio)), None)
    if audio is not None:
        return MediaType.VOICE if audio.voice else MediaType.AUDIO
    return MediaType.DOCUMENT
