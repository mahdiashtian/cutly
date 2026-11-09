from __future__ import annotations

from core.clock import utcnow
from schemas.broadcast import DashboardStats
from services.base import Service


class StatsService(Service):
    """Admin numbers are always computed live from SQL (one statement), never
    cached: they are read rarely and must be exact when they are."""

    async def dashboard(self) -> DashboardStats:
        async with self._uow() as uow:
            return await uow.stats.dashboard(utcnow())
