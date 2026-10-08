"""SQLAlchemy analytics, access logs and broadcast reports."""

from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select, update, case, true
from core.cache import get_cache
from core.maintenance import database_operation
from core.database import session_scope
from core.models import BroadcastJob, File, FileAccessLog, User


@database_operation
async def touch_user_activity(user_id: int) -> None:
    timestamp = datetime.now(timezone.utc)
    async with session_scope() as session:
        persisted = await session.scalar(
            update(User)
            .where(User.userid == user_id)
            .values(
                last_activity_at=case(
                    (
                        (User.last_activity_at.is_(None))
                        | (User.last_activity_at < timestamp),
                        timestamp,
                    ),
                    else_=User.last_activity_at,
                )
            )
            .returning(User.last_activity_at)
        )
    if persisted is not None:
        await get_cache().update_user_activity(user_id, persisted.isoformat())


async def record_file_access(viewer_id: int, file: File) -> None:
    async with session_scope() as session:
        session.add(
            FileAccessLog(
                viewer_id=viewer_id, file_code=file.code, owner_id=file.owner_id
            )
        )


async def get_user_access_page(user_id: int, page: int, page_size: int = 10):
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.userid == user_id))
        total = (
            await session.scalar(
                select(func.count(func.distinct(FileAccessLog.file_code))).where(
                    FileAccessLog.viewer_id == user_id
                )
            )
            or 0
        )
        last_viewed = func.max(FileAccessLog.accessed_at).label("last_viewed")
        stmt = (
            select(
                FileAccessLog.file_code,
                func.count(FileAccessLog.id).label("view_count"),
                last_viewed,
            )
            .where(FileAccessLog.viewer_id == user_id)
            .group_by(FileAccessLog.file_code)
            .order_by(last_viewed.desc())
            .offset(max(page, 0) * page_size)
            .limit(page_size)
        )
        rows = [dict(row) for row in (await session.execute(stmt)).mappings().all()]
        return rows, total, user


async def get_dashboard_statistics() -> dict:
    now = datetime.now(timezone.utc)
    today, recent_week, previous_week = (
        now - timedelta(days=1),
        now - timedelta(days=7),
        now - timedelta(days=14),
    )

    def conditional_count(condition):
        return func.count(case((condition, 1)))

    users = select(
        func.count(User.id).label("total_users"),
        conditional_count(User.created_at >= today).label("new_today"),
        conditional_count(User.created_at >= recent_week).label("current_users"),
        conditional_count(
            (User.created_at >= previous_week) & (User.created_at < recent_week)
        ).label("previous_users"),
    ).subquery("user_stats")
    files = select(
        func.count(File.id).label("total_files"),
        conditional_count(File.created_at >= today).label("files_today"),
        func.coalesce(func.sum(File.count), 0).label("downloads"),
    ).subquery("file_stats")
    broadcasts = (
        select(
            func.count(BroadcastJob.id).label("broadcasts"),
            func.coalesce(func.sum(BroadcastJob.success_count), 0).label("delivered"),
            func.coalesce(func.sum(BroadcastJob.total_count), 0).label("attempted"),
        )
        .where(BroadcastJob.status == "completed")
        .subquery("broadcast_stats")
    )
    views = (
        select(func.count(FileAccessLog.id))
        .where(FileAccessLog.accessed_at >= today)
        .scalar_subquery()
    )
    # One SQL statement gives one MVCC snapshot and avoids four network trips.
    stmt = select(users, files, broadcasts, views.label("views_today")).select_from(
        users.join(files, true()).join(broadcasts, true())
    )
    async with session_scope() as session:
        result = dict((await session.execute(stmt)).mappings().one())
    result["week_growth"] = result.pop("current_users") - result.pop("previous_users")
    attempted, delivered = result.pop("attempted"), result.pop("delivered")
    result["delivery_rate"] = delivered / attempted * 100 if attempted else 0.0
    return result


async def create_broadcast_job(
    *, admin_id, delivery_type, audience, scheduled_at=None
) -> BroadcastJob:
    async with session_scope() as session:
        job = BroadcastJob(
            admin_id=admin_id,
            delivery_type=delivery_type,
            audience=audience,
            scheduled_at=scheduled_at,
            status="scheduled" if scheduled_at else "running",
            started_at=None if scheduled_at else datetime.now(timezone.utc),
        )
        session.add(job)
        await session.flush()
        return job


async def finish_broadcast_job(
    job: BroadcastJob, *, total, success, failed, cancelled=False
) -> None:
    values = dict(
        status="cancelled" if cancelled else "completed",
        total_count=total,
        success_count=success,
        failed_count=failed,
        completed_at=datetime.now(timezone.utc),
    )
    async with session_scope() as session:
        await session.execute(
            update(BroadcastJob).where(BroadcastJob.id == job.id).values(**values)
        )
    for key, value in values.items():
        setattr(job, key, value)
