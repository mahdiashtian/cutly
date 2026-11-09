from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, func, select, true

from core.enums import BroadcastStatus
from db.models import Broadcast, Link, LinkView, User
from repositories.postgres.base import SqlRepository
from schemas.broadcast import DashboardStats


class StatsRepository(SqlRepository):
    async def dashboard(self, now: datetime) -> DashboardStats:
        """Every number in ONE statement: one round trip, one consistent snapshot."""
        day, week, two_weeks = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=14)

        def count_if(condition):
            return func.count(case((condition, 1)))

        users = select(
            func.count().label("total_users"),
            count_if(User.created_at >= day).label("new_today"),
            count_if(User.created_at >= week).label("this_week"),
            count_if((User.created_at >= two_weeks) & (User.created_at < week)).label("last_week"),
        ).select_from(User).subquery()
        links = select(
            func.count().label("total_links"),
            count_if(Link.created_at >= day).label("links_today"),
            func.coalesce(func.sum(Link.download_count), 0).label("downloads"),
        ).select_from(Link).subquery()
        broadcasts = select(
            func.count().label("broadcasts"),
            func.coalesce(func.sum(Broadcast.succeeded), 0).label("delivered"),
            func.coalesce(func.sum(Broadcast.total), 0).label("attempted"),
        ).where(Broadcast.status == BroadcastStatus.COMPLETED).subquery()
        views = select(func.count()).select_from(LinkView).where(LinkView.viewed_at >= day).scalar_subquery()

        row = (await self._session.execute(
            select(users, links, broadcasts, views.label("views_today"))
            .select_from(users.join(links, true()).join(broadcasts, true()))
        )).mappings().one()
        attempted = int(row["attempted"])
        return DashboardStats(
            total_users=row["total_users"], new_today=row["new_today"],
            week_growth=row["this_week"] - row["last_week"],
            total_links=row["total_links"], links_today=row["links_today"],
            downloads=int(row["downloads"]), views_today=row["views_today"],
            broadcasts=row["broadcasts"],
            delivery_rate=int(row["delivered"]) / attempted * 100 if attempted else 0.0,
        )
