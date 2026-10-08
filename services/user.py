"""User services with the existing Redis cache-first contract."""

from datetime import datetime
from core.cache import get_cache
from core.maintenance import database_operation
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


@database_operation
async def userid_list() -> list[int]:
    cache = get_cache()
    ids = await cache.get_user_list()
    if ids is not None:
        return ids
    async with cache.fill_lock("users"):
        ids = await cache.get_user_list()
        if ids is not None:
            return ids
        version = await cache.version("users")
        ids = await _repo.get_userids_list()
        await cache.set_user_list(ids, version=version)
        merged = await cache.get_user_list()
        return merged if merged is not None else ids


@database_operation
async def read_users(is_admin: bool = False, **filters) -> list[User]:
    cache = get_cache()
    if is_admin:
        ids = await cache.get_admin_list()
        if ids is not None:
            return await _repo.get_admins()
    version = await cache.version("admins") if is_admin else None
    users = await _repo.get_filtered(is_admin=is_admin, **filters)
    if is_admin:
        await cache.set_admin_list([user.userid for user in users], version=version)
    return users


@database_operation
async def read_user_from_db(user_id: int) -> User | None:
    cache = get_cache()
    cached = await _cached_user(cache, user_id)
    if cached is not None:
        return cached
    async with cache.fill_lock(f"user:{user_id}"):
        cached = await _cached_user(cache, user_id)
        if cached is not None:
            return cached
        version = await cache.user_version(user_id)
        user = await _repo.get_by_userid(user_id)
        if user is not None:
            await cache.set_user_detail(user_id, _cache_data(user), version=version)
        return user


async def _cached_user(cache, user_id):
    data = await cache.get_user_detail(user_id)
    # Legacy cached entries lacked the PK/timestamps. Hydrate those once.
    if data and data.get("id") is not None and data.get("created_at"):
        try:
            data = dict(data)
            for key in ("created_at", "last_activity_at"):
                data[key] = datetime.fromisoformat(data[key]) if data.get(key) else None
            return User(**data)
        except (ValueError, TypeError):
            await cache.invalidate_user_detail(user_id)
    return None


@database_operation
async def create_user_from_db(data: dict) -> User:
    cache = get_cache()
    version = await cache.user_version(data["userid"])
    user, created = await _repo.get_or_create_user(
        data["userid"],
        defaults={key: value for key, value in data.items() if key != "userid"},
    )
    if created:
        await cache.set_user_detail(user.userid, _cache_data(user), version=version)
    return user


async def change_admin_from_db(
    userid: int, *, is_superuser=None, is_staff=None
) -> bool:
    return await _repo.set_admin_status(
        userid, is_superuser=is_superuser, is_staff=is_staff
    )
