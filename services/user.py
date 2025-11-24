"""User management services with Redis caching layer.

This module provides user management functions with Redis caching for
high-performance read operations. Cache-first strategy reduces database
load significantly for frequently accessed user lists.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from tortoise.expressions import Q

from core.cache import get_cache
from core.models import User

LOGGER = logging.getLogger(__name__)


async def userid_list() -> List[int]:
    """Return cached Telegram IDs for all known users.
    
    Uses Redis cache for fast access. Falls back to database if cache miss.
    Automatically updates cache after database read.
    
    Returns:
        List of Telegram user IDs.
        
    Examples:
        >>> ids = await userid_list()
        >>> isinstance(ids, list)
        True
    """
    cache = get_cache()
    
    # Try cache first
    cached_ids = await cache.get_user_list()
    if cached_ids is not None:
        return cached_ids
    
    # Cache miss - read from database
    result = await User.all().values_list("userid", flat=True)
    user_ids = list(result)
    
    # Update cache for next time
    await cache.set_user_list(user_ids)
    
    return user_ids


async def read_users(is_admin: bool = False) -> List[User]:
    """Return ordered list of users with Redis caching.

    Uses Redis cache for admin lists. Regular users are fetched from database
    as they need full User objects with relationships.

    Args:
        is_admin: When ``True`` returns only staff or superusers.

    Returns:
        Sorted list of ``User`` records.
        
    Examples:
        >>> users = await read_users()
        >>> admins = await read_users(is_admin=True)
    """
    cache = get_cache()
    
    # For admin list, try cache first
    if is_admin:
        cached_admin_ids = await cache.get_admin_list()
        if cached_admin_ids is not None:
            # Fetch User objects for cached IDs
            users = await User.filter(userid__in=cached_admin_ids).order_by("id")
            return list(users)
    
    # Cache miss or regular user list - read from database
    queryset = User.all()
    if is_admin:
        queryset = queryset.filter(Q(is_superuser=True) | Q(is_staff=True))
    
    users = await queryset.order_by("id")
    
    # Update cache for admin list
    if is_admin:
        admin_ids = [user.userid for user in users]
        await cache.set_admin_list(admin_ids)
    
    return users


async def read_user_from_db(user_id: int) -> Optional[User]:
    """Fetch a single user by Telegram ID with caching.
    
    Checks Redis cache first for user details, falls back to database.
    
    Args:
        user_id: Telegram user ID.
        
    Returns:
        User instance or None if not found.
        
    Examples:
        >>> user = await read_user_from_db(12345678)
    """
    cache = get_cache()
    
    # Try cache first
    cached_data = await cache.get_user_detail(user_id)
    if cached_data:
        # Reconstruct User object from cached data
        user = User(**cached_data)
        return user
    
    # Cache miss - read from database
    user = await User.filter(userid=user_id).first()
    
    # Update cache if user found
    if user:
        user_data = {
            "userid": user.userid,
            "phone_number": user.phone_number,
            "is_superuser": user.is_superuser,
            "is_staff": user.is_staff,
        }
        await cache.set_user_detail(user_id, user_data)
    
    return user


async def create_user_from_db(data: Dict[str, Any]) -> User:
    """Persist a new user record or return existing user with cache update.
    
    Automatically adds new user to Redis cache for immediate availability
    in subsequent requests.
    
    Args:
        data: User data dictionary containing 'userid' key.
        
    Returns:
        User instance (newly created or existing).
        
    Raises:
        IntegrityError: If data violates database constraints other than userid uniqueness.
        
    Examples:
        >>> user = await create_user_from_db({"userid": 12345678})
    """
    cache = get_cache()
    
    userid = data["userid"]
    # Remove userid from defaults to avoid duplicate keyword argument
    defaults = {k: v for k, v in data.items() if k != "userid"}
    user, created = await User.get_or_create(userid=userid, defaults=defaults)
    
    # If new user created, add to cache
    if created:
        # Add to user list cache
        await cache.add_user_to_list(userid)
        
        # Cache user details
        user_data = {
            "userid": user.userid,
            "phone_number": user.phone_number,
            "is_superuser": user.is_superuser,
            "is_staff": user.is_staff,
        }
        await cache.set_user_detail(userid, user_data)
        
        LOGGER.info(f"New user {userid} added to cache")
    
    return user


async def change_admin_from_db(
    userid: int,
    *,
    is_superuser: Optional[bool] = None,
    is_staff: Optional[bool] = None,
) -> bool:
    """Update administrative flags for a user with cache refresh.
    
    Invalidates admin cache to ensure updated permissions are reflected
    immediately in subsequent requests.
    
    Args:
        userid: Telegram user ID.
        is_superuser: Optional superuser flag.
        is_staff: Optional staff flag.
        
    Returns:
        True if user was found and updated, False otherwise.
        
    Examples:
        >>> success = await change_admin_from_db(12345678, is_staff=True)
    """
    cache = get_cache()
    
    # Get user from DB directly (bypass cache for update operations)
    user = await User.filter(userid=userid).first()
    if not user:
        return False
    
    if is_superuser is not None:
        user.is_superuser = is_superuser
    if is_staff is not None:
        user.is_staff = is_staff
    
    await user.save()
    
    # Update cached user details
    user_data = {
        "userid": user.userid,
        "phone_number": user.phone_number,
        "is_superuser": user.is_superuser,
        "is_staff": user.is_staff,
    }
    await cache.set_user_detail(userid, user_data)
    
    # Rebuild admin list cache immediately
    admin_users = await User.filter(Q(is_superuser=True) | Q(is_staff=True)).all()
    admin_ids = [u.userid for u in admin_users]
    await cache.set_admin_list(admin_ids)
    
    LOGGER.info(f"Admin status updated for user {userid}, admin cache rebuilt with {len(admin_ids)} admins")
    
    return True

