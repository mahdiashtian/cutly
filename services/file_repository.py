"""File repository implementation."""

from __future__ import annotations

from typing import List, Optional

from core.models import File
from services.repository import BaseRepository


class FileRepository(BaseRepository[File]):
    """Repository for File model with custom query methods."""

    def __init__(self) -> None:
        """Initialize File repository."""
        super().__init__(File)

    async def get_by_code(self, code: str, owner_id: Optional[int] = None) -> Optional[File]:
        """Get file by its unique code.
        
        Args:
            code: File unique code.
            owner_id: Optional owner filter.
            
        Returns:
            File instance or None if not found.
            
        Examples:
            >>> repo = FileRepository()
            >>> file = await repo.get_by_code("abc123")
        """
        queryset = self.model.filter(code=code)
        if owner_id is not None:
            queryset = queryset.filter(owner_id=owner_id)
        return await queryset.select_related("owner").first()  # Optimize with select_related

    async def get_user_files(
        self,
        owner_id: int,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[File]:
        """Get files owned by a user with pagination.
        
        Args:
            owner_id: Owner's Telegram user ID.
            limit: Optional maximum number of files to return.
            offset: Number of files to skip.
            
        Returns:
            List of File instances.
            
        Examples:
            >>> repo = FileRepository()
            >>> files = await repo.get_user_files(12345678, limit=10)
        """
        queryset = self.model.filter(owner_id=owner_id).order_by("-created_at")
        
        if limit is not None:
            queryset = queryset.limit(limit).offset(offset)
        
        return await queryset.select_related("owner")  # Optimize query

    async def get_filtered(
        self,
        file_type: Optional[str] = None,
        owner_id: Optional[int] = None,
        has_password: Optional[bool] = None,
        **filters
    ) -> List[File]:
        """Get files filtered by custom criteria.
        
        Args:
            file_type: Filter by file type (photo, video, etc.).
            owner_id: Filter by owner ID.
            has_password: Filter by password protection status.
            
        Returns:
            List of matching File instances.
            
        Examples:
            >>> repo = FileRepository()
            >>> photos = await repo.get_filtered(file_type="photo")
        """
        queryset = self.model.all()
        
        if file_type:
            queryset = queryset.filter(type=file_type)
        
        if owner_id is not None:
            queryset = queryset.filter(owner_id=owner_id)
        
        if has_password is not None:
            if has_password:
                queryset = queryset.exclude(password=None)
            else:
                queryset = queryset.filter(password=None)
        
        return await queryset.select_related("owner").order_by("-created_at")

    async def delete_by_code(self, code: str, owner_id: int) -> bool:
        """Delete a file by code and owner.
        
        Args:
            code: File unique code.
            owner_id: Owner's Telegram user ID.
            
        Returns:
            True if deleted, False if not found.
            
        Examples:
            >>> repo = FileRepository()
            >>> success = await repo.delete_by_code("abc123", 12345678)
        """
        deleted_count = await self.model.filter(
            code=code,
            owner_id=owner_id
        ).delete()
        return bool(deleted_count)

    async def increment_download_count(self, code: str) -> bool:
        """Increment the download count for a file.
        
        Args:
            code: File unique code.
            
        Returns:
            True if incremented, False if file not found.
            
        Examples:
            >>> repo = FileRepository()
            >>> success = await repo.increment_download_count("abc123")
        """
        file = await self.get_by_code(code)
        if not file:
            return False
        
        file.count += 1
        await file.save(update_fields=["count"])  # Only update count field
        return True

    async def get_popular_files(self, limit: int = 10) -> List[File]:
        """Get most downloaded files.
        
        Args:
            limit: Maximum number of files to return.
            
        Returns:
            List of File instances ordered by download count.
            
        Examples:
            >>> repo = FileRepository()
            >>> popular = await repo.get_popular_files(10)
        """
        return await self.model.all().order_by("-count").limit(limit).select_related("owner")

