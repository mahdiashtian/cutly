"""Channel persistence, preserving Redis invalidation after mutations."""

from sqlalchemy import delete, or_, select
from core.cache import get_cache
from core.database import session_scope
from core.models import Channel
from core.maintenance import database_operation

_revision = 0


def channel_revision():
    return _revision


async def read_channels_from_db() -> list[Channel]:
    async with session_scope() as session:
        return list((await session.scalars(select(Channel))).all())


@database_operation
async def delete_channel_from_db(channel_identifier: str) -> bool:
    global _revision
    async with session_scope() as session:
        result = await session.execute(
            delete(Channel).where(
                or_(
                    Channel.channel_id == channel_identifier,
                    Channel.channel_link == channel_identifier,
                )
            )
        )
        deleted = bool(result.rowcount)
    if deleted:
        _revision += 1
        await get_cache().invalidate_channel_cache()
    return deleted


@database_operation
async def create_channel_from_db(data: dict) -> Channel:
    global _revision
    async with session_scope() as session:
        channel = Channel(**data)
        session.add(channel)
        await session.flush()
    _revision += 1
    await get_cache().invalidate_channel_cache()
    return channel
