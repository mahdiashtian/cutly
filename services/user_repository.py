"""User persistence through SQLAlchemy."""

from sqlalchemy import or_, select, update, delete
from core.cache import get_cache
from core.maintenance import database_operation
from core.database import session_scope
from core.models import User
from services.repository import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self):
        super().__init__(User)

    async def get_by_userid(self, userid):
        return await self.first(User.userid == userid)

    async def get_or_create_user(self, userid, defaults=None):
        return await self.get_or_create(defaults=defaults, userid=userid)

    async def get_admins(self):
        return await self.list(
            or_(User.is_superuser.is_(True), User.is_staff.is_(True)),
            order_by=(User.id,),
        )

    async def get_filtered(self, **filters):
        conditions = []
        if filters.get("is_admin"):
            conditions.append(or_(User.is_superuser.is_(True), User.is_staff.is_(True)))
        if filters.get("created_after"):
            conditions.append(User.created_at >= filters["created_after"])
        if filters.get("active_after"):
            conditions.append(User.last_activity_at >= filters["active_after"])
        if filters.get("inactive_before"):
            conditions.append(
                or_(
                    User.last_activity_at.is_(None),
                    User.last_activity_at < filters["inactive_before"],
                )
            )
        return await self.list(*conditions, order_by=(User.id,))

    async def get_userids_list(self):
        async with session_scope() as session:
            return list(
                (await session.scalars(select(User.userid).order_by(User.id))).all()
            )

    @database_operation
    async def create(self, data):
        user = await super().create(data)
        cache = get_cache()
        await cache.add_user_to_list(user.userid, rank=user.id)
        if user.is_staff or user.is_superuser:
            await cache.invalidate_scope("admins")
        return user

    @database_operation
    async def update(self, id, data):
        async with session_scope() as session:
            user = await session.get(User, id)
            if user is None:
                return None
            previous = user.userid
            for key, value in data.items():
                setattr(user, key, value)
            await session.flush()
        cache = get_cache()
        for userid in {previous, user.userid}:
            await cache.invalidate_user_detail(userid)
        await cache.invalidate_scope("admins")
        if previous != user.userid:
            await cache.invalidate_user_index()
        return user

    @database_operation
    async def update_where(self, data, *conditions):
        async with session_scope() as session:
            previous = (
                list(
                    await session.scalars(
                        select(User.userid).where(*conditions).with_for_update()
                    )
                )
                if "userid" in data
                else []
            )
            userids = list(
                await session.scalars(
                    update(User)
                    .where(*conditions)
                    .values(**data)
                    .returning(User.userid)
                )
            )
        cache = get_cache()
        for userid in set(previous + userids):
            await cache.invalidate_user_detail(userid)
        if userids:
            await cache.invalidate_scope("admins")
            if "userid" in data:
                await cache.invalidate_user_index()
        return len(userids)

    @database_operation
    async def delete_where(self, *conditions):
        async with session_scope() as session:
            userids = list(
                await session.scalars(
                    delete(User).where(*conditions).returning(User.userid)
                )
            )
        cache = get_cache()
        for userid in userids:
            await cache.invalidate_user_detail(userid)
        if userids:
            await cache.invalidate_user_index()
            await cache.invalidate_scope("admins")
        return bool(userids)

    async def set_admin_status(self, userid, *, is_superuser=None, is_staff=None):
        changes = {}
        if is_superuser is not None:
            changes["is_superuser"] = is_superuser
        if is_staff is not None:
            changes["is_staff"] = is_staff
        if changes:
            return bool(await self.update_where(changes, User.userid == userid))
        return await self.exists(userid=userid)
