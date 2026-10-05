from datetime import datetime, timedelta, timezone
from core.database import session_scope
from core.models import FileAccessLog
from services import (
    create_broadcast_job,
    finish_broadcast_job,
    get_dashboard_statistics,
    get_user_access_page,
    record_file_access,
)
from services.user_repository import UserRepository


async def test_empty_statistics():
    stats = await get_dashboard_statistics()
    assert stats == dict(
        total_users=0,
        new_today=0,
        week_growth=0,
        total_files=0,
        files_today=0,
        downloads=0,
        views_today=0,
        broadcasts=0,
        delivery_rate=0.0,
    )


async def test_unique_access_logs_pagination_and_unknown_user(make_file, owner):
    first = await make_file("first")
    second = await make_file("second")
    await record_file_access(owner.userid, first)
    await record_file_access(owner.userid, first)
    await record_file_access(owner.userid, second)
    rows, total, user = await get_user_access_page(owner.userid, -1, 1)
    assert total == 2 and user.id == owner.id and rows[0]["file_code"] == "second"
    assert rows[0]["last_viewed"].tzinfo is not None
    rows, total, _ = await get_user_access_page(owner.userid, 1, 1)
    assert rows[0]["view_count"] == 2 and rows[0]["file_code"] == "first"
    assert (await get_user_access_page(9999, 0)) == ([], 0, None)


async def test_dashboard_rolling_windows_and_completed_broadcasts(make_file, owner):
    now = datetime.now(timezone.utc)
    await UserRepository().create({"userid": 42, "created_at": now - timedelta(days=8)})
    await UserRepository().create(
        {"userid": 43, "created_at": now - timedelta(days=20)}
    )
    file = await make_file(count=7)
    await make_file("old", count=3, created_at=now - timedelta(days=2))
    await record_file_access(owner.userid, file)
    completed = await create_broadcast_job(
        admin_id=999, delivery_type="copy", audience="all"
    )
    assert completed.status == "running" and completed.started_at.tzinfo
    await finish_broadcast_job(completed, total=10, success=8, failed=2)
    cancelled = await create_broadcast_job(
        admin_id=999, delivery_type="forward", audience="all"
    )
    await finish_broadcast_job(cancelled, total=5, success=2, failed=1, cancelled=True)
    scheduled = await create_broadcast_job(
        admin_id=999,
        delivery_type="copy",
        audience="all",
        scheduled_at=now + timedelta(days=1),
    )
    assert scheduled.status == "scheduled" and scheduled.started_at is None
    stats = await get_dashboard_statistics()
    assert stats == dict(
        total_users=3,
        new_today=1,
        week_growth=0,
        total_files=2,
        files_today=1,
        downloads=10,
        views_today=1,
        broadcasts=1,
        delivery_rate=80.0,
    )
