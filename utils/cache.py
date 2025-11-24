"""Simple in-memory caching layer."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar("T")


class SimpleCache:
    """Simple in-memory cache with TTL support.
    
    This is a lightweight caching solution that doesn't require Redis.
    For production, consider using Redis or Memcached.
    
    Examples:
        >>> cache = SimpleCache(ttl=300)  # 5 minutes TTL
        >>> cache.set("key", "value")
        >>> value = cache.get("key")
    """

    def __init__(self, ttl: int = 300) -> None:
        """Initialize cache with time-to-live.
        
        Args:
            ttl: Time-to-live in seconds (default: 300).
        """
        self._cache: Dict[str, tuple[Any, float]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired.
        
        Args:
            key: Cache key.
            
        Returns:
            Cached value or None if not found or expired.
        """
        if key not in self._cache:
            return None
        
        value, expiry = self._cache[key]
        if time.time() > expiry:
            del self._cache[key]
            return None
        
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL.
        
        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Optional custom TTL (uses default if not provided).
        """
        expiry = time.time() + (ttl if ttl is not None else self._ttl)
        self._cache[key] = (value, expiry)

    def delete(self, key: str) -> None:
        """Delete key from cache.
        
        Args:
            key: Cache key to delete.
        """
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached items."""
        self._cache.clear()

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], T],
        ttl: Optional[int] = None
    ) -> T:
        """Get value from cache or compute and cache it.
        
        Args:
            key: Cache key.
            factory: Function to compute value if not cached.
            ttl: Optional custom TTL.
            
        Returns:
            Cached or computed value.
            
        Examples:
            >>> cache = SimpleCache()
            >>> value = cache.get_or_set("key", lambda: expensive_computation())
        """
        value = self.get(key)
        if value is None:
            value = factory()
            self.set(key, value, ttl)
        return value

    async def async_get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: Optional[int] = None
    ) -> Any:
        """Async version of get_or_set.
        
        Args:
            key: Cache key.
            factory: Async function to compute value if not cached.
            ttl: Optional custom TTL.
            
        Returns:
            Cached or computed value.
            
        Examples:
            >>> cache = SimpleCache()
            >>> value = await cache.async_get_or_set("key", async_computation)
        """
        value = self.get(key)
        if value is None:
            value = await factory()
            self.set(key, value, ttl)
        return value


# Global cache instance
_global_cache = SimpleCache(ttl=300)


def get_cache() -> SimpleCache:
    """Get global cache instance.
    
    Returns:
        Global SimpleCache instance.
        
    Examples:
        >>> from utils.cache import get_cache
        >>> cache = get_cache()
        >>> cache.set("key", "value")
    """
    return _global_cache

