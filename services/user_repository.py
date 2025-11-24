"""User repository implementation."""

from __future__ import annotations

from typing import List, Optional

from tortoise.expressions import Q

from core.models import User
from services.repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User model with custom query methods."""

    def __init__(self) -> None:
        """Initialize User repository."""
        super().__init__(User)

    async def get_by_userid(self, userid: int) -> Optional[User]:
        """Get user by Telegram user ID.
        
        Args:
            userid: Telegram user ID.
            
        Returns:
            User instance or None if not found.
            
        Examples:
            >>> repo = UserRepository()
            >>> user = await repo.get_by_userid(12345678)
        """
        return await self.model.filter(userid=userid).first()

    async def get_or_create_user(self, userid: int, defaults: Optional[dict] = None) -> tuple[User, bool]:
        """Get existing user or create a new one.
        
        Args:
            userid: Telegram user ID.
            defaults: Default values for new user creation.
            
        Returns:
            Tuple of (User instance, created flag).
            
        Examples:
            >>> repo = UserRepository()
            >>> user, created = await repo.get_or_create_user(12345678)
        """
        return await self.model.get_or_create(
            userid=userid,
            defaults=defaults or {}
        )

    async def get_admins(self) -> List[User]:
        """Get all admin users (superusers or staff).
        
        Returns:
            List of admin User instances.
            
        Examples:
            >>> repo = UserRepository()
            >>> admins = await repo.get_admins()
        """
        return await self.model.filter(
            Q(is_superuser=True) | Q(is_staff=True)
        ).order_by("id")

    async def get_filtered(self, **filters) -> List[User]:
        """Get users filtered by custom criteria.
        
        Args:
            is_admin: Filter for admin users.
            created_after: Filter by creation date.
            
        Returns:
            List of matching User instances.
        """
        queryset = self.model.all()
        
        if filters.get("is_admin"):
            queryset = queryset.filter(Q(is_superuser=True) | Q(is_staff=True))
        
        if filters.get("created_after"):
            queryset = queryset.filter(created_at__gte=filters["created_after"])
        
        return await queryset.order_by("id")

    async def get_userids_list(self) -> List[int]:
        """Get list of all Telegram user IDs.
        
        Returns:
            List of Telegram user IDs.
            
        Examples:
            >>> repo = UserRepository()
            >>> ids = await repo.get_userids_list()
        """
        result = await self.model.all().values_list("userid", flat=True)
        return list(result)

    async def set_admin_status(
        self,
        userid: int,
        *,
        is_superuser: Optional[bool] = None,
        is_staff: Optional[bool] = None
    ) -> bool:
        """Update user's admin status.
        
        Args:
            userid: Telegram user ID.
            is_superuser: Optional superuser flag.
            is_staff: Optional staff flag.
            
        Returns:
            True if user was found and updated, False otherwise.
            
        Examples:
            >>> repo = UserRepository()
            >>> success = await repo.set_admin_status(12345678, is_staff=True)
        """
        user = await self.get_by_userid(userid)
        if not user:
            return False
        
        if is_superuser is not None:
            user.is_superuser = is_superuser
        if is_staff is not None:
            user.is_staff = is_staff
        
        await user.save()
        return True

