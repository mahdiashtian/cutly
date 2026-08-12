"""Analytics, access-log, and broadcast-report persistence helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from tortoise.functions import Count, Max, Sum

from core.models import BroadcastJob, File, FileAccessLog, User


async def touch_user_activity(user_id: int) -> None:
    """Record the last time a user interacted with the bot."""
    await User.filter(userid=user_id).update(last_activity_at=datetime.now(timezone.utc))


async def record_file_access(viewer_id: int, file: File) -> None:
    """Persist a successful link view for paginated admin reporting."""
    await FileAccessLog.create(
        viewer_id=viewer_id,
        file_code=file.code,
        owner_id=file.owner_id,
    )


async def get_user_access_page(
    user_id: int, page: int, page_size: int = 10
) -> Tuple[List[Dict[str, Any]], int, Optional[User]]:
    """Return a page of unique file links viewed by a user and their totals."""
    safe_page = max(page, 0)
    user = await User.filter(userid=user_id).first()
    grouped = FileAccessLog.filter(viewer_id=user_id).group_by("file_code").annotate(
        view_count=Count("id"),
        last_viewed=Max("accessed_at"),
    )
    # Tortoise's ``count`` with ``GROUP BY`` is backend-dependent; retrieving
    # only the distinct code field gives a correct page count on both DBs.
    # ``distinct()`` must precede ``values()`` — ``ValuesQuery`` has no
    # ``distinct()`` method of its own, only a ``distinct`` bool attribute.
    total = len(await FileAccessLog.filter(viewer_id=user_id).distinct().values("file_code"))
    rows = await grouped.order_by("-last_viewed").offset(safe_page * page_size).limit(page_size).values(
        "file_code", "view_count", "last_viewed"
    )
    return rows, total, user


async def get_dashboard_statistics() -> Dict[str, Any]:
    """Calculate the aggregate metrics shown in the admin dashboard."""
    now = datetime.now(timezone.utc)
    today = now - timedelta(days=1)
    recent_week = now - timedelta(days=7)
    previous_week = now - timedelta(days=14)

    total_users = await User.all().count()
    new_today = await User.filter(created_at__gte=today).count()
    current_week_users = await User.filter(created_at__gte=recent_week).count()
    previous_week_users = await User.filter(
        created_at__gte=previous_week, created_at__lt=recent_week
    ).count()
    total_files = await File.all().count()
    files_today = await File.filter(created_at__gte=today).count()
    download_rows = await File.all().annotate(total=Sum("count")).values("total")
    downloads = (download_rows[0]["total"] if download_rows else 0) or 0
    views_today = await FileAccessLog.filter(accessed_at__gte=today).count()
    broadcasts = await BroadcastJob.filter(status="completed").count()
    delivered_rows = await BroadcastJob.filter(status="completed").annotate(
        total=Sum("success_count")
    ).values("total")
    attempted_rows = await BroadcastJob.filter(status="completed").annotate(
        total=Sum("total_count")
    ).values("total")
    delivered = (delivered_rows[0]["total"] if delivered_rows else 0) or 0
    attempted = (attempted_rows[0]["total"] if attempted_rows else 0) or 0

    return {
        "total_users": total_users,
        "new_today": new_today,
        "week_growth": current_week_users - previous_week_users,
        "total_files": total_files,
        "files_today": files_today,
        "downloads": downloads,
        "views_today": views_today,
        "broadcasts": broadcasts,
        "delivery_rate": (delivered / attempted * 100) if attempted else 0.0,
    }


async def create_broadcast_job(
    *,
    admin_id: int,
    delivery_type: str,
    audience: str,
    scheduled_at: Optional[datetime] = None,
) -> BroadcastJob:
    """Create a persisted audit record for a broadcast."""
    return await BroadcastJob.create(
        admin_id=admin_id,
        delivery_type=delivery_type,
        audience=audience,
        scheduled_at=scheduled_at,
        status="scheduled" if scheduled_at else "running",
        started_at=None if scheduled_at else datetime.now(timezone.utc),
    )


async def finish_broadcast_job(
    job: BroadcastJob, *, total: int, success: int, failed: int, cancelled: bool = False
) -> None:
    """Persist a broadcast outcome."""
    job.status = "cancelled" if cancelled else "completed"
    job.total_count = total
    job.success_count = success
    job.failed_count = failed
    job.completed_at = datetime.now(timezone.utc)
    await job.save(update_fields=[
        "status", "total_count", "success_count", "failed_count", "completed_at"
    ])
