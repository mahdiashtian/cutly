from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update

from core.enums import BroadcastAudience
from db.models import User
from repositories.postgres.base import SqlRepository
from schemas.broadcast import Recipient
from schemas.user import UserDTO, UserProfile

NEW_USER_WINDOW = timedelta(days=7)
ACTIVE_USER_WINDOW = timedelta(days=30)


class UserRepository(SqlRepository):
    async def get(self, user_id: int) -> UserDTO | None:
        row = await self._session.get(User, user_id)
        return UserDTO.model_validate(row) if row else None

    async def profile(self, user_id: int) -> UserProfile | None:
        row = await self._session.get(User, user_id)
        return UserProfile.model_validate(row) if row else None

    async def insert_if_missing(self, user_id: int, access_hash: int | None) -> UserDTO:
        """Idempotent create: two concurrent first messages cannot both fail."""
        statement = (
            self._insert(User.__table__)
            .values(id=user_id, access_hash=access_hash, is_admin=False)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await self._session.execute(statement)
        return await self.get(user_id)

    async def update(self, user_id: int, **values) -> UserDTO | None:
        result = await self._session.execute(
            update(User).where(User.id == user_id).values(**values).returning(User)
        )
        row = result.scalar_one_or_none()
        return UserDTO.model_validate(row) if row else None

    async def touch(self, user_id: int, when: datetime) -> None:
        """Hot path: a plain UPDATE, no RETURNING of a row nobody reads."""
        await self._session.execute(update(User).where(User.id == user_id).values(last_active_at=when))

    async def admin_ids(self) -> list[int]:
        # Bare boolean condition so it matches the partial index predicate.
        result = await self._session.scalars(select(User.id).where(User.is_admin).order_by(User.id))
        return list(result)

    # ---- broadcast audiences (keyset pagination: constant memory, no OFFSET) ----
    def _audience_filter(self, audience: BroadcastAudience, now: datetime):
        if audience is BroadcastAudience.NEW:
            return User.created_at >= now - NEW_USER_WINDOW
        if audience is BroadcastAudience.ACTIVE:
            return User.last_active_at >= now - ACTIVE_USER_WINDOW
        if audience is BroadcastAudience.INACTIVE:
            return or_(User.last_active_at.is_(None), User.last_active_at < now - ACTIVE_USER_WINDOW)
        return None  # ALL and CHANNEL start from every user

    async def count_audience(self, audience: BroadcastAudience, now: datetime) -> int:
        statement = select(func.count()).select_from(User)
        condition = self._audience_filter(audience, now)
        if condition is not None:
            statement = statement.where(condition)
        return int(await self._session.scalar(statement))

    async def audience_page(
        self, audience: BroadcastAudience, now: datetime, *, after_id: int | None, limit: int
    ) -> list[Recipient]:
        statement = select(User.id, User.access_hash).order_by(User.id).limit(limit)
        condition = self._audience_filter(audience, now)
        if condition is not None:
            statement = statement.where(condition)
        if after_id is not None:
            statement = statement.where(User.id > after_id)
        rows = await self._session.execute(statement)
        return [Recipient(id=row.id, access_hash=row.access_hash) for row in rows]
