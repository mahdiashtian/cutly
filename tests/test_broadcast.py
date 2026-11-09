from __future__ import annotations

from datetime import timedelta

from telethon.errors import FloodWaitError, UserIsBlockedError

from core.clock import utcnow
from core.enums import BroadcastAudience, BroadcastMode, BroadcastStatus
from tests.conftest import FakeClient
from worker.jobs.broadcast import run_broadcast

ADMIN = 1
RECIPIENTS = [101, 102, 103, 104, 105]


async def _setup(container, **overrides):
    for user_id in [ADMIN, *RECIPIENTS]:
        await container.users.ensure(user_id, access_hash=user_id * 10)
    values = dict(admin_id=ADMIN, mode=BroadcastMode.COPY, audience=BroadcastAudience.ALL, channel_ref=None,
                  source_chat_id=ADMIN, source_message_id=55)
    values.update(overrides)
    return await container.broadcasts.create(**values)


async def test_broadcast_delivers_reports_and_counts_failures(container):
    broadcast = await _setup(container)
    client = FakeClient(fail_for={103: UserIsBlockedError(request=None), 104: FloodWaitError(request=None, capture=0)})

    assert await run_broadcast(container, client, broadcast.id)

    copied_to = sorted(m.chat_id for m in client.sent if m.text == "<copy>")
    assert copied_to == [ADMIN, 101, 102, 104, 105]  # the admin is a user too; 104 retried after the flood
    done = await container.broadcasts.get(broadcast.id)
    assert (done.status, done.succeeded, done.failed, done.cursor) == (BroadcastStatus.COMPLETED, 5, 1, 105)
    report = [m for m in client.sent if m.chat_id == ADMIN and m.file is not None]
    assert len(report) == 1 and not report[0].file.exists()  # sent, then removed from disk
    assert client.edits  # progress was reported


async def test_cancel_stops_at_the_next_checkpoint(container):
    container.settings.broadcast_page_size = 2
    broadcast = await _setup(container)
    await container.broadcasts.claim(broadcast)  # make it RUNNING so cancel flags it
    await container.broadcasts.cancel_active()
    async with container.database.sessionmaker() as session, session.begin():
        from db.models import Broadcast
        (await session.get(Broadcast, broadcast.id)).status = BroadcastStatus.QUEUED

    await run_broadcast(container, FakeClient(), broadcast.id)
    done = await container.broadcasts.get(broadcast.id)
    assert done.status is BroadcastStatus.CANCELLED and done.succeeded == 2  # only the first page of 6


async def test_only_one_broadcast_runs_at_a_time(container):
    first, second = await _setup(container), await _setup(container)
    assert await container.broadcasts.claim(first) is True
    assert await container.broadcasts.claim(second) is None  # partial unique index
    assert await container.broadcasts.collect_runnable() == []
    await container.broadcasts.finish(first.id, BroadcastStatus.COMPLETED)
    assert await container.broadcasts.collect_runnable() == [second.id]


async def test_scheduled_and_orphaned_jobs_are_collected(container):
    due = await _setup(container, scheduled_at=utcnow() - timedelta(minutes=1))
    later = await _setup(container, scheduled_at=utcnow() + timedelta(days=1))
    assert await container.broadcasts.collect_runnable() == [due.id]
    assert (await container.broadcasts.get(later.id)).status is BroadcastStatus.SCHEDULED

    # A RUNNING job whose worker stopped sending heartbeats is queued again.
    assert await container.broadcasts.claim(await container.broadcasts.get(due.id))
    async with container.database.sessionmaker() as session, session.begin():
        from db.models import Broadcast
        (await session.get(Broadcast, due.id)).heartbeat_at = utcnow() - timedelta(hours=1)
    assert await container.broadcasts.collect_runnable() == [due.id]


async def test_cancel_drops_pending_jobs(container):
    scheduled = await _setup(container, scheduled_at=utcnow() + timedelta(days=1))
    assert await container.broadcasts.cancel_active() == 1
    assert (await container.broadcasts.get(scheduled.id)).status is BroadcastStatus.CANCELLED
