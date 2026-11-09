"""Sending one broadcast: paced, resumable, cancellable, with a CSV report."""
from __future__ import annotations

import asyncio
import csv
import logging
from pathlib import Path

from telethon import TelegramClient
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
    UserNotParticipantError,
)
from telethon.tl.custom import Message

from bot import texts
from bot.telegram import user_peer
from container import Container
from core.enums import BroadcastAudience, BroadcastMode, BroadcastStatus
from schemas.broadcast import BroadcastDTO, Recipient
from schemas.channel import chat_peer

log = logging.getLogger(__name__)

# The recipient can never receive messages from us: do not retry.
PERMANENT_ERRORS = (
    UserIsBlockedError, PeerIdInvalidError, InputUserDeactivatedError, UserDeactivatedError,
    UserDeactivatedBanError, ChatWriteForbiddenError, ValueError,
)
# Network or Telegram hiccups: worth another attempt.
TRANSIENT_ERRORS = (asyncio.TimeoutError, OSError, TimedOutError, ServerError, RpcCallFailError)
MAX_ATTEMPTS = 3
SKIPPED = object()


class Pacer:
    """Spaces out send *starts* to a fixed rate, shared by all concurrent sends.

    A FloodWait pauses everyone at once, which is what Telegram asks for. One
    broadcast runs at a time (enforced by the database), so a local pacer is
    enough — no distributed rate limiter is needed.
    """

    def __init__(self, rate_per_second: float) -> None:
        self._interval = 1 / max(rate_per_second, 0.1)
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            start = max(loop.time(), self._next)
            self._next = start + self._interval
        await asyncio.sleep(max(0.0, start - loop.time()))

    def pause(self, seconds: float) -> None:
        self._next = max(self._next, asyncio.get_running_loop().time() + seconds)


class BroadcastRunner:
    def __init__(self, container: Container, client: TelegramClient, broadcast: BroadcastDTO) -> None:
        self._container = container
        self._service = container.broadcasts
        self._client = client
        self._broadcast = broadcast
        self._settings = container.settings
        self._pacer = Pacer(self._settings.broadcast_rate_per_second)
        self._report = Path(self._settings.backup_dir) / f"broadcast-{broadcast.id}.csv"

    async def run(self) -> None:
        broadcast = self._broadcast
        admin = await self._container.users.get(broadcast.admin_id)
        self._admin_peer = user_peer(broadcast.admin_id, admin.access_hash if admin else None)
        source = await self._load_source()
        if source is None:
            await self._service.finish(broadcast.id, BroadcastStatus.FAILED)
            await self._client.send_message(self._admin_peer, texts.BROADCAST_FAILED)
            return
        status_message_id = broadcast.status_message_id or await self._post_status()
        ok, failed, cursor = broadcast.succeeded, broadcast.failed, broadcast.cursor
        cancelled = False
        while not cancelled:
            page = await self._service.recipients(
                broadcast, after_id=cursor, limit=self._settings.broadcast_page_size
            )
            if not page:
                break
            outcomes = await asyncio.gather(*(self._deliver(source, recipient) for recipient in page))
            rows = [(r.id, outcome) for r, outcome in zip(page, outcomes, strict=True) if outcome is not SKIPPED]
            ok += sum(1 for _, error in rows if error is None)
            failed += sum(1 for _, error in rows if error is not None)
            self._append_report(rows)
            cursor = page[-1].id
            cancelled = await self._service.checkpoint(broadcast.id, cursor=cursor, succeeded=ok, failed=failed)
            await self._edit_status(status_message_id, texts.BROADCAST_PROGRESS.format(
                done=ok + failed, total=broadcast.total, ok=ok, failed=failed))

        await self._service.finish(broadcast.id, BroadcastStatus.CANCELLED if cancelled else BroadcastStatus.COMPLETED)
        label = texts.BROADCAST_CANCELLED_LABEL if cancelled else texts.BROADCAST_DONE_LABEL
        await self._edit_status(status_message_id, texts.BROADCAST_FINISHED.format(
            label=label, ok=ok, failed=failed, done=ok + failed, total=broadcast.total))
        await self._send_report()

    async def _load_source(self) -> Message | None:
        broadcast = self._broadcast
        if broadcast.source_message_id is None:
            return None
        return await self._client.get_messages(self._admin_peer, ids=broadcast.source_message_id)

    async def _post_status(self) -> int:
        message = await self._client.send_message(
            self._admin_peer, texts.BROADCAST_STARTED.format(total=self._broadcast.total)
        )
        await self._service.set_status_message(self._broadcast.id, message.id)
        return message.id

    async def _deliver(self, source: Message, recipient: Recipient):
        """``None`` on success, an error string on failure, SKIPPED for non-members."""
        peer = user_peer(recipient.id, recipient.access_hash)
        broadcast = self._broadcast
        if broadcast.audience is BroadcastAudience.CHANNEL:
            await self._pacer.wait()  # the membership check is a Telegram request too
            if not await self._is_member(recipient.id):
                return SKIPPED
        for attempt in range(MAX_ATTEMPTS):
            await self._pacer.wait()
            try:
                if broadcast.mode is BroadcastMode.FORWARD:
                    await self._client.forward_messages(peer, source)
                else:
                    await self._client.send_message(peer, source)  # copies text, media and entities
                return None
            except FloodWaitError as error:
                log.warning("flood wait %ss during broadcast %s", error.seconds, broadcast.id)
                self._pacer.pause(error.seconds + 1)
            except PERMANENT_ERRORS as error:
                return type(error).__name__
            except TRANSIENT_ERRORS as error:
                if attempt == MAX_ATTEMPTS - 1:
                    return type(error).__name__
                await asyncio.sleep(2 * (attempt + 1))
            except Exception as error:  # noqa: BLE001 - one recipient never stops the broadcast
                return f"{type(error).__name__}: {error}"
        return "retries exhausted"

    async def _is_member(self, user_id: int) -> bool:
        try:
            await self._client.get_permissions(chat_peer(self._broadcast.channel_ref or ""), user_id)
            return True
        except (UserNotParticipantError, ValueError):
            return False
        except Exception:  # noqa: BLE001
            log.warning("membership check failed for %s", user_id, exc_info=True)
            return False

    def _append_report(self, rows: list[tuple[int, str | None]]) -> None:
        """Appended per page, so a resumed broadcast keeps the earlier rows."""
        self._report.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self._report.exists()
        with self._report.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if is_new:
                handle.write("﻿")  # BOM: Excel then reads the Persian text correctly
                writer.writerow(["user_id", "status", "error"])
            for user_id, error in rows:
                writer.writerow([user_id, texts.BROADCAST_OK if error is None else texts.BROADCAST_ERROR, error or ""])

    async def _edit_status(self, message_id: int, text: str) -> None:
        try:
            await self._client.edit_message(self._admin_peer, message_id, text)
        except Exception:  # noqa: BLE001 - progress is cosmetic
            log.debug("could not edit broadcast status", exc_info=True)

    async def _send_report(self) -> None:
        if not self._report.exists():
            return
        try:
            await self._client.send_file(self._admin_peer, self._report, caption=texts.BROADCAST_REPORT)
        finally:
            self._report.unlink(missing_ok=True)


async def run_broadcast(container: Container, client: TelegramClient, broadcast_id: int) -> bool:
    """Claim and run one broadcast. Returns whether it ran."""
    broadcast = await container.broadcasts.get(broadcast_id)
    if broadcast is None or broadcast.status is not BroadcastStatus.QUEUED:
        return False
    if not await container.broadcasts.claim(broadcast):
        return False  # another one is running; Beat will queue this one later
    broadcast = await container.broadcasts.get(broadcast_id)
    try:
        await BroadcastRunner(container, client, broadcast).run()
    except Exception:
        log.exception("broadcast %s failed", broadcast_id)
        await container.broadcasts.finish(broadcast_id, BroadcastStatus.FAILED)
        try:
            await client.send_message(broadcast.admin_id, texts.BROADCAST_FAILED)
        except Exception:  # noqa: BLE001
            log.warning("could not notify admin about broadcast %s", broadcast_id)
    return True
