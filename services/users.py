from __future__ import annotations

from redis.exceptions import RedisError

from core.clock import utcnow
from repositories.postgres.unit_of_work import UnitOfWorkFactory
from repositories.redis.caches import UserCache
from repositories.redis.markers import ActivityThrottle
from schemas.user import UserDTO, UserProfile
from services.base import Service


class UserService(Service):
    def __init__(
        self, uow: UnitOfWorkFactory, cache: UserCache, throttle: ActivityThrottle,
        *, admin_master: int | None,
    ) -> None:
        super().__init__(uow)
        self._cache = cache
        self._throttle = throttle
        self._admin_master = admin_master

    async def get(self, user_id: int) -> UserDTO | None:
        async def read_db() -> UserDTO | None:
            async with self._uow() as uow:
                return await uow.users.get(user_id)

        async def write_cache(user: UserDTO | None) -> None:
            # Unknown users are not negative-cached: they are created right after.
            if user is not None:
                await self._cache.set(user)

        return await self._cached(
            read_cache=lambda: self._cache.get(user_id), read_db=read_db, write_cache=write_cache
        )

    async def ensure(self, user_id: int, access_hash: int | None = None) -> UserDTO:
        """Return the user, creating it on first contact, and record activity.

        Hot path (every private message): normally one Redis GET plus one
        ``SET NX`` and no SQL at all.
        """
        user = await self.get(user_id)
        if user is None or (access_hash is not None and user.access_hash != access_hash):
            async with self._uow() as uow:
                user = await uow.users.insert_if_missing(user_id, access_hash)
                if access_hash is not None and user.access_hash != access_hash:
                    user = await uow.users.update(user_id, access_hash=access_hash)
            await self._safe(self._cache.set(user))
        await self._touch(user_id)
        return user

    async def _touch(self, user_id: int) -> None:
        try:
            if not await self._throttle.should_touch(user_id):
                return
        except RedisError:
            return  # activity is best-effort; never fail a message over it
        async with self._uow() as uow:
            await uow.users.update(user_id, last_active_at=utcnow())

    async def is_admin(self, user_id: int) -> bool:
        if user_id == self._admin_master:
            return True
        user = await self.get(user_id)
        return bool(user and user.is_admin)

    async def set_admin(self, user_id: int, value: bool) -> bool:
        """Only users who already started the bot can be promoted (as before)."""
        async with self._uow() as uow:
            user = await uow.users.update(user_id, is_admin=value)
        if user is None:
            return False
        await self._safe(self._cache.set(user))
        return True

    async def profile(self, user_id: int) -> UserProfile | None:
        async with self._uow() as uow:
            return await uow.users.profile(user_id)

    async def admin_ids(self) -> list[int]:
        async with self._uow() as uow:
            return await uow.users.admin_ids()
