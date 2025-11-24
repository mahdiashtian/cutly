"""Dependency injection container."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar("T")


class Container:
    """Simple dependency injection container.
    
    This implements the Dependency Injection pattern to manage
    dependencies and make testing easier.
    
    Examples:
        >>> container = Container()
        >>> container.register("db", lambda: Database())
        >>> db = container.resolve("db")
    """

    def __init__(self) -> None:
        """Initialize empty container."""
        self._services: Dict[str, Callable[[], Any]] = {}
        self._singletons: Dict[str, Any] = {}

    def register(
        self,
        name: str,
        factory: Callable[[], T],
        singleton: bool = False
    ) -> None:
        """Register a service with its factory.
        
        Args:
            name: Service identifier.
            factory: Factory function to create the service.
            singleton: If True, only one instance will be created.
            
        Examples:
            >>> container = Container()
            >>> container.register("cache", SimpleCache, singleton=True)
        """
        self._services[name] = factory
        if singleton:
            self._singletons[name] = None

    def resolve(self, name: str) -> Any:
        """Resolve and return a service instance.
        
        Args:
            name: Service identifier.
            
        Returns:
            Service instance.
            
        Raises:
            KeyError: If service is not registered.
            
        Examples:
            >>> container = Container()
            >>> cache = container.resolve("cache")
        """
        if name not in self._services:
            raise KeyError(f"Service '{name}' not registered")
        
        # Return cached singleton if exists
        if name in self._singletons:
            if self._singletons[name] is None:
                self._singletons[name] = self._services[name]()
            return self._singletons[name]
        
        # Create new instance
        return self._services[name]()

    def has(self, name: str) -> bool:
        """Check if a service is registered.
        
        Args:
            name: Service identifier.
            
        Returns:
            True if service is registered, False otherwise.
        """
        return name in self._services

    def reset(self) -> None:
        """Reset all services (useful for testing)."""
        self._services.clear()
        self._singletons.clear()


# Global container instance
_container = Container()


def get_container() -> Container:
    """Get global dependency injection container.
    
    Returns:
        Global Container instance.
        
    Examples:
        >>> from app.container import get_container
        >>> container = get_container()
        >>> cache = container.resolve("cache")
    """
    return _container


def setup_container() -> None:
    """Setup and configure the dependency injection container.
    
    This function registers all services with the container.
    Should be called once during application startup.
    
    Examples:
        >>> setup_container()
        >>> container = get_container()
        >>> user_repo = container.resolve("user_repository")
    """
    from services.file_repository import FileRepository
    from services.user_repository import UserRepository
    from utils.cache import SimpleCache
    
    container = get_container()
    
    # Register repositories as singletons
    container.register("user_repository", UserRepository, singleton=True)
    container.register("file_repository", FileRepository, singleton=True)
    
    # Register cache as singleton
    container.register("cache", lambda: SimpleCache(ttl=300), singleton=True)

