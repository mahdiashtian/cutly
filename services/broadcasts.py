from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from core.clock import utcnow
from core.enums import BroadcastAudience, BroadcastMode, BroadcastStatus
from schemas.broadcast import BroadcastDTO, Recipient
from services.base import Service

# A running job checkpoints every page; this much silence means its worker died.
STALE_AFTER = timedelta(minutes=10)


class BroadcastService(Service):
    # ---- used by the bot ----
    async def create(
        self, *, admin_id: int, mode: BroadcastMode, audience: BroadcastAudience,
        channel_ref: str | None, source_chat_id: int, source_message_id: int,
        scheduled_at: datetime | None = None,
    ) -> BroadcastDTO:
        status = BroadcastStatus.SCHEDULED if scheduled_at else BroadcastStatus.QUEUED
        async with self._uow() as uow:
            return await uow.broadcasts.create(
                admin_id=admin_id, mode=mode, audience=audience, channel_ref=channel_ref,
                source_chat_id=source_chat_id, source_message_id=source_message_id,
                status=status, scheduled_at=scheduled_at,
            )

    async def audience_size(self, audience: BroadcastAudience) -> int:
        async with self._uow() as uow:
            return await uow.users.count_audience(audience, utcnow())

    async def cancel_active(self) -> int:
        async with self._uow() as uow:
            return await uow.broadcasts.request_cancel_active(utcnow())

    async def has_running(self) -> bool:
        async with self._uow() as uow:
            return await uow.broadcasts.has_running()

    # ---- used by the worker ----
    async def get(self, broadcast_id: int) -> BroadcastDTO | None:
        async with self._uow() as uow:
            return await uow.broadcasts.get(broadcast_id)

    async def claim(self, broadcast: BroadcastDTO) -> bool | None:
        """``True`` claimed, ``False`` nothing to do, ``None`` another job is running."""
        try:
            async with self._uow() as uow:
                total = await uow.users.count_audience(broadcast.audience, utcnow())
                return await uow.broadcasts.claim(broadcast.id, total=total, now=utcnow())
        except IntegrityError:
            return None

    async def recipients(self, broadcast: BroadcastDTO, *, after_id: int | None, limit: int) -> list[Recipient]:
        async with self._uow() as uow:
            return await uow.users.audience_page(broadcast.audience, utcnow(), after_id=after_id, limit=limit)

    async def checkpoint(self, broadcast_id: int, *, cursor: int | None, succeeded: int, failed: int) -> bool:
        async with self._uow() as uow:
            return await uow.broadcasts.checkpoint(
                broadcast_id, cursor=cursor, succeeded=succeeded, failed=failed, now=utcnow()
            )

    async def set_status_message(self, broadcast_id: int, message_id: int) -> None:
        async with self._uow() as uow:
            await uow.broadcasts.set_status_message(broadcast_id, message_id)

    async def finish(self, broadcast_id: int, status: BroadcastStatus) -> None:
        async with self._uow() as uow:
            await uow.broadcasts.finish(broadcast_id, status, utcnow())

    async def collect_runnable(self) -> list[int]:
        """Move due and orphaned jobs to QUEUED; return the next one to start.

        Only one id, and only when nothing is running: broadcasts run one at a
        time, so enqueueing more would just pile up tasks that do nothing.
        """
        now = utcnow()
        async with self._uow() as uow:
            await uow.broadcasts.queue_due(now)
            await uow.broadcasts.requeue_stale(now - STALE_AFTER)
            if await uow.broadcasts.has_running():
                return []
            return (await uow.broadcasts.queued_ids())[:1]
