"""User persistence through SQLAlchemy."""

from sqlalchemy import or_, select
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
        return await self.list(*conditions, order_by=(User.id,))

    async def get_userids_list(self):
        async with session_scope() as session:
            return list((await session.scalars(select(User.userid))).all())

    async def set_admin_status(self, userid, *, is_superuser=None, is_staff=None):
        user = await self.get_by_userid(userid)
        if user is None:
            return False
        changes = {}
        if is_superuser is not None:
            changes["is_superuser"] = is_superuser
        if is_staff is not None:
            changes["is_staff"] = is_staff
        if changes:
            await self.update(user.id, changes)
        return True
