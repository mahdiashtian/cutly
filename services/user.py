"""User services with the existing Redis cache-first contract."""

from datetime import datetime
from core.cache import get_cache
from core.models import User
from services.user_repository import UserRepository

_repo = UserRepository()


def _cache_data(user):
    return {
        "id": user.id,
        "userid": user.userid,
        "phone_number": user.phone_number,
        "is_superuser": user.is_superuser,
        "is_staff": user.is_staff,
        "created_at": user.created_at.isoformat(),
        "last_activity_at": user.last_activity_at.isoformat()
        if user.last_activity_at
        else None,
    }


async def userid_list() -> list[int]:
    cache = get_cache()
    ids = await cache.get_user_list()
    if ids is not None:
        return ids
    ids = await _repo.get_userids_list()
    await cache.set_user_list(ids)
    return ids


async def read_users(is_admin: bool = False) -> list[User]:
    cache = get_cache()
    if is_admin:
        ids = await cache.get_admin_list()
        if ids is not None:
            return await _repo.list(User.userid.in_(ids), order_by=(User.id,))
    users = await _repo.get_filtered(is_admin=is_admin)
    if is_admin:
        await cache.set_admin_list([user.userid for user in users])
    return users


async def read_user_from_db(user_id: int) -> User | None:
    cache = get_cache()
    data = await cache.get_user_detail(user_id)
    # Legacy cached entries lacked the PK/timestamps. Hydrate those once.
    if data and data.get("id") is not None and data.get("created_at"):
        data = dict(data)
        for key in ("created_at", "last_activity_at"):
            data[key] = datetime.fromisoformat(data[key]) if data.get(key) else None
        return User(**data)
    version = await cache.version("user")
    user = await _repo.get_by_userid(user_id)
    if user is not None:
        # A concurrent role edit must not be overwritten by a stale cache fill.
        await cache.set_user_detail(user_id, _cache_data(user), version=version)
    return user


async def create_user_from_db(data: dict) -> User:
    cache = get_cache()
    user, created = await _repo.get_or_create_user(
        data["userid"],
        defaults={key: value for key, value in data.items() if key != "userid"},
    )
    if created:
        await cache.add_user_to_list(user.userid)
        await cache.set_user_detail(user.userid, _cache_data(user))
    return user


async def change_admin_from_db(
    userid: int, *, is_superuser=None, is_staff=None
) -> bool:
    if not await _repo.set_admin_status(
        userid, is_superuser=is_superuser, is_staff=is_staff
    ):
        return False
    user = await _repo.get_by_userid(userid)
    cache = get_cache()
    await cache.invalidate_scope("user")
    await cache.set_user_detail(userid, _cache_data(user))
    await cache.set_admin_list([admin.userid for admin in await _repo.get_admins()])
    return True
