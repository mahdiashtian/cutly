"""Sending a link's media back by Telegram file id (no download, no re-upload)."""
from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.errors import FileReferenceEmptyError, FileReferenceExpiredError, FileReferenceInvalidError
from telethon.tl.custom import Message
from telethon.tl.types import InputDocument, InputPhoto

from core.enums import MediaType
from schemas.link import LinkDTO, MediaDTO
from services.links import LinkService

log = logging.getLogger(__name__)
_REFERENCE_ERRORS = (FileReferenceExpiredError, FileReferenceInvalidError, FileReferenceEmptyError)


class DeliveryError(RuntimeError):
    """Nothing could be sent."""


class LinkDelivery:
    def __init__(self, client: TelegramClient, links: LinkService, *, storage_channel_id: int) -> None:
        self._client = client
        self._links = links
        self._storage_channel_id = storage_channel_id

    async def send(self, chat_id: int, link: LinkDTO, caption: str) -> list[Message]:
        """Photos and videos go out as albums (Telethon splits them into tens);
        other media types cannot share an album and are sent one by one.

        Every item carries the caption. One failing item does not stop the rest;
        only a delivery where nothing at all was sent is an error.
        """
        groupable = [item for item in link.media if item.media_type.groups_in_album]
        singles = [item for item in link.media if not item.media_type.groups_in_album]
        sent: list[Message] = []
        if len(groupable) > 1:
            try:
                sent += await self._send(chat_id, link, groupable, caption)
            except Exception:  # noqa: BLE001 - fall back to one-by-one below
                log.warning("album send failed for %s; sending items one by one", link.code, exc_info=True)
                singles = groupable + singles
        else:
            singles = groupable + singles
        for item in sorted(singles, key=lambda media: media.position):
            try:
                sent += await self._send(chat_id, link, [item], caption)
            except Exception:  # noqa: BLE001
                log.warning("sending media %s of %s failed", item.id, link.code, exc_info=True)
        if not sent:
            raise DeliveryError(link.code)
        return sent

    async def _send(self, chat_id: int, link: LinkDTO, items: list[MediaDTO], caption: str) -> list[Message]:
        try:
            return await self._send_once(chat_id, items, caption)
        except _REFERENCE_ERRORS:
            # File references expire; the storage-channel copy gives a fresh one.
            return await self._send_once(chat_id, await self._refresh(link, items), caption)

    async def _send_once(self, chat_id: int, items: list[MediaDTO], caption: str) -> list[Message]:
        media = [_input_media(item) for item in items]
        if len(media) == 1:
            return [await self._client.send_file(chat_id, media[0], caption=caption)]
        return list(await self._client.send_file(chat_id, media, caption=[caption] * len(media)))

    async def _refresh(self, link: LinkDTO, items: list[MediaDTO]) -> list[MediaDTO]:
        if not self._storage_channel_id:
            raise DeliveryError("storage channel is not configured")
        messages = await self._client.get_messages(
            self._storage_channel_id, ids=[item.storage_message_id for item in items]
        )
        refreshed = []
        for item, message in zip(items, messages, strict=True):
            source = None
            if message is not None:
                source = message.photo if item.media_type is MediaType.PHOTO else message.document
            if source is None or source.id != item.tg_file_id:
                raise DeliveryError(f"storage copy of media {item.id} is missing or changed")
            await self._links.refresh_media_reference(link, item.id, source.access_hash, source.file_reference)
            refreshed.append(item.model_copy(update={
                "tg_access_hash": source.access_hash, "tg_file_reference": source.file_reference,
            }))
        return refreshed


def _input_media(item: MediaDTO) -> InputPhoto | InputDocument:
    cls = InputPhoto if item.media_type is MediaType.PHOTO else InputDocument
    return cls(id=item.tg_file_id, access_hash=item.tg_access_hash, file_reference=item.tg_file_reference)
