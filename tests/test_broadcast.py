import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from telethon.errors import FloodWaitError, UserIsBlockedError
from telethon.errors.common import InvalidBufferError
from utils import helpers


@pytest.fixture
def fast_sleep(monkeypatch):
    original = asyncio.sleep

    async def fast(delay):
        await original(0)

    monkeypatch.setattr(helpers.asyncio, "sleep", fast)


async def test_deliveries_isolate_permanent_failures_and_report(fast_sleep):
    outcomes = []

    async def send(user_id):
        if user_id == 2:
            raise UserIsBlockedError(request=None)

    async def report(user_id, success, error):
        outcomes.append((user_id, success, error))

    result = await helpers.broadcast_to_users(
        None,
        [SimpleNamespace(userid=x) for x in (1, 2, 3)],
        send,
        batch_size=1,
        delay_between_batches=0,
        on_delivery=report,
    )
    assert result == (2, 1) and len(outcomes) == 3
    assert [row[0] for row in outcomes if not row[1]] == [2]


async def test_transient_retry_releases_semaphore(fast_sleep):
    attempts = {}

    async def send(user_id):
        attempts[user_id] = attempts.get(user_id, 0) + 1
        if attempts[user_id] == 1:
            raise OSError("temporary")

    result = await helpers.broadcast_to_users(
        None,
        [SimpleNamespace(userid=x) for x in range(6)],
        send,
        max_concurrent=1,
        max_retries=1,
    )
    assert result == (6, 0) and all(count == 2 for count in attempts.values())


@pytest.mark.parametrize(
    "error",
    [FloodWaitError(request=None, capture=0), InvalidBufferError(b"\x00\x00\x00\x00")],
)
async def test_exhausted_flood_or_buffer_failure_is_counted(fast_sleep, error):
    send = AsyncMock(side_effect=error)
    outcomes = []
    result = await helpers.broadcast_to_users(
        None,
        [SimpleNamespace(userid=1)],
        send,
        max_retries=0,
        on_delivery=lambda *values: outcomes.append(values),
    )
    assert result == (0, 1) and len(outcomes) == 1


async def test_reporting_failure_does_not_change_delivery(fast_sleep):
    reporter = AsyncMock(side_effect=RuntimeError("report failed"))
    result = await helpers.broadcast_to_users(
        None, [SimpleNamespace(userid=1)], AsyncMock(), on_delivery=reporter
    )
    assert result == (1, 0)


async def test_cancelled_queue_sends_nothing(fast_sleep):
    cancel = asyncio.Event()
    cancel.set()
    send = AsyncMock()
    assert await helpers.broadcast_to_users(
        None, [SimpleNamespace(userid=1)], send, cancel_event=cancel
    ) == (0, 0)
    send.assert_not_awaited()


@pytest.mark.parametrize(
    "kwargs", [{"max_concurrent": 0}, {"batch_size": 0}, {"max_retries": -1}]
)
async def test_invalid_broadcast_options(kwargs):
    with pytest.raises(ValueError):
        await helpers.broadcast_to_users(None, [], AsyncMock(), **kwargs)


async def test_professional_copy_forward_and_csv(
    app, owner, event_factory, telegram, monkeypatch
):
    async def deliver(client, users, callback, **kwargs):
        for user in users:
            await callback(user.userid)
            await kwargs["on_delivery"](user.userid, True, None)
        return len(users), 0

    monkeypatch.setattr(app, "broadcast_to_users", deliver)
    for delivery_type in ("copy", "forward"):
        draft = app.BroadcastDraft(
            admin_id=999,
            message=SimpleNamespace(chat_id=999),
            delivery_type=delivery_type,
            users=[owner],
        )
        await app.execute_professional_broadcast(draft)
        assert not app.BROADCAST_IN_PROGRESS and app.BROADCAST_CANCEL_EVENT is None
        report = telegram.send_file.call_args.args[1]
        assert "user_id,status,error" in report.getvalue().decode("utf-8-sig")
    telegram.forward_messages.assert_awaited_once()
    from services import get_dashboard_statistics

    assert (await get_dashboard_statistics())["broadcasts"] == 2
