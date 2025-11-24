"""Base repository pattern implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, TypeVar

from tortoise.models import Model

T = TypeVar("T", bound=Model)


class BaseRepository(ABC, Generic[T]):
    """Abstract base repository for database operations.
    
    This implements the Repository Pattern to abstract database operations
    and provide a clean interface for data access.
    
    Type Parameters:
        T: The model type this repository manages.
    """

    def __init__(self, model: type[T]) -> None:
        """Initialize repository with model class.
        
        Args:
            model: The Tortoise ORM model class.
        """
        self.model = model

    async def get_by_id(self, id: int) -> Optional[T]:
        """Get a record by its primary key.
        
        Args:
            id: Primary key value.
            
        Returns:
            Model instance or None if not found.
        """
        return await self.model.filter(id=id).first()

    async def get_all(self) -> List[T]:
        """Get all records.
        
        Returns:
            List of all model instances.
        """
        return await self.model.all()

    async def create(self, data: Dict[str, Any]) -> T:
        """Create a new record.
        
        Args:
            data: Dictionary of field values.
            
        Returns:
            Newly created model instance.
        """
        return await self.model.create(**data)

    async def update(self, id: int, data: Dict[str, Any]) -> Optional[T]:
        """Update a record by ID.
        
        Args:
            id: Primary key value.
            data: Dictionary of fields to update.
            
        Returns:
            Updated model instance or None if not found.
        """
        instance = await self.get_by_id(id)
        if not instance:
            return None
        await instance.update_from_dict(data)
        await instance.save()
        return instance

    async def delete(self, id: int) -> bool:
        """Delete a record by ID.
        
        Args:
            id: Primary key value.
            
        Returns:
            True if deleted, False if not found.
        """
        deleted_count = await self.model.filter(id=id).delete()
        return bool(deleted_count)

    async def exists(self, **filters: Any) -> bool:
        """Check if a record exists with given filters.
        
        Args:
            **filters: Filter conditions.
            
        Returns:
            True if exists, False otherwise.
        """
        return await self.model.filter(**filters).exists()

    async def count(self, **filters: Any) -> int:
        """Count records matching filters.
        
        Args:
            **filters: Filter conditions.
            
        Returns:
            Number of matching records.
        """
        return await self.model.filter(**filters).count()

    @abstractmethod
    async def get_filtered(self, **filters: Any) -> List[T]:
        """Get records filtered by custom criteria.
        
        This method should be implemented by subclasses for model-specific queries.
        
        Args:
            **filters: Custom filter parameters.
            
        Returns:
            List of matching model instances.
        """
        pass

