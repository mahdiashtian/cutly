from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from core.enums import BroadcastStatus
from db.models import Broadcast
from repositories.postgres.base import SqlRepository
from schemas.broadcast import BroadcastDTO


class BroadcastRepository(SqlRepository):
    async def create(self, **values) -> BroadcastDTO:
        broadcast = Broadcast(**values)
        self._session.add(broadcast)
        await self._session.flush()
        return BroadcastDTO.model_validate(broadcast)

    async def get(self, broadcast_id: int) -> BroadcastDTO | None:
        row = await self._session.get(Broadcast, broadcast_id)
        return BroadcastDTO.model_validate(row) if row else None

    async def has_running(self) -> bool:
        found = await self._session.scalar(
            select(Broadcast.id).where(Broadcast.status == BroadcastStatus.RUNNING).limit(1)
        )
        return found is not None

    async def claim(self, broadcast_id: int, *, total: int, now: datetime) -> bool:
        """QUEUED -> RUNNING. Raises IntegrityError when another one is running
        (the partial unique index), which the caller turns into a retry."""
        result = await self._session.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id, Broadcast.status == BroadcastStatus.QUEUED)
            .values(status=BroadcastStatus.RUNNING, total=total, heartbeat_at=now,
                    started_at=now)
        )
        return bool(result.rowcount)

    async def checkpoint(
        self, broadcast_id: int, *, cursor: int | None, succeeded: int, failed: int, now: datetime
    ) -> bool:
        """Persist progress and return whether cancellation was requested: one
        round trip does both the heartbeat and the cancel check."""
        result = await self._session.execute(
            update(Broadcast).where(Broadcast.id == broadcast_id)
            .values(cursor=cursor, succeeded=succeeded, failed=failed, heartbeat_at=now)
            .returning(Broadcast.cancel_requested)
        )
        return bool(result.scalar_one_or_none())

    async def set_status_message(self, broadcast_id: int, message_id: int) -> None:
        await self._session.execute(
            update(Broadcast).where(Broadcast.id == broadcast_id).values(status_message_id=message_id)
        )

    async def finish(self, broadcast_id: int, status: BroadcastStatus, now: datetime) -> None:
        await self._session.execute(
            update(Broadcast).where(Broadcast.id == broadcast_id)
            .values(status=status, finished_at=now, heartbeat_at=now)
        )

    async def request_cancel_active(self, now: datetime) -> int:
        """Scheduled/queued jobs are cancelled outright; a running one is flagged
        and stops at its next checkpoint."""
        pending = await self._session.execute(
            update(Broadcast)
            .where(Broadcast.status.in_((BroadcastStatus.SCHEDULED, BroadcastStatus.QUEUED)))
            .values(status=BroadcastStatus.CANCELLED, finished_at=now)
        )
        running = await self._session.execute(
            update(Broadcast).where(Broadcast.status == BroadcastStatus.RUNNING)
            .values(cancel_requested=True)
        )
        return int(pending.rowcount or 0) + int(running.rowcount or 0)

    async def queue_due(self, now: datetime) -> list[int]:
        """SCHEDULED -> QUEUED for every job whose time has come."""
        result = await self._session.execute(
            update(Broadcast)
            .where(Broadcast.status == BroadcastStatus.SCHEDULED, Broadcast.scheduled_at <= now)
            .values(status=BroadcastStatus.QUEUED)
            .returning(Broadcast.id)
        )
        return list(result.scalars())

    async def requeue_stale(self, heartbeat_before: datetime) -> list[int]:
        """A RUNNING job whose worker died stops sending heartbeats; put it back
        in the queue so it resumes from its cursor."""
        result = await self._session.execute(
            update(Broadcast)
            .where(Broadcast.status == BroadcastStatus.RUNNING, Broadcast.heartbeat_at < heartbeat_before)
            .values(status=BroadcastStatus.QUEUED)
            .returning(Broadcast.id)
        )
        return list(result.scalars())

    async def queued_ids(self) -> list[int]:
        result = await self._session.scalars(
            select(Broadcast.id).where(Broadcast.status == BroadcastStatus.QUEUED).order_by(Broadcast.id)
        )
        return list(result)
