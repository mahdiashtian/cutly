"""Redis connection pool (redis.asyncio)."""
from __future__ import annotations

from redis.asyncio import BlockingConnectionPool, Redis

# A caller waits this long for a free connection instead of failing at once:
# a burst then queues for milliseconds rather than turning into a wall of cache
# errors that dumps the whole burst onto the database.
POOL_WAIT_SECONDS = 5
# Without socket timeouts a silently dropped connection hangs every caller.
SOCKET_TIMEOUT_SECONDS = 5


class RedisClient:
    """Owns one connection pool for the process lifetime.

    ``decode_responses=True``: every value we store is text (JSON or a number).
    """

    def __init__(self, url: str, *, max_connections: int = 64) -> None:
        self._pool = BlockingConnectionPool.from_url(
            url,
            max_connections=max_connections,
            timeout=POOL_WAIT_SECONDS,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
            socket_timeout=SOCKET_TIMEOUT_SECONDS,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        self.client: Redis = Redis(connection_pool=self._pool)

    async def close(self) -> None:
        await self.client.aclose()
        await self._pool.disconnect()
