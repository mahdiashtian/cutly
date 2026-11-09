"""Unit of Work: one session and one transaction shared by every repository."""
from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repositories.postgres.broadcasts import BroadcastRepository
from repositories.postgres.channels import ChannelRepository
from repositories.postgres.links import LinkRepository
from repositories.postgres.settings import SettingsRepository
from repositories.postgres.stats import StatsRepository
from repositories.postgres.users import UserRepository


class UnitOfWork:
    """``async with uow:`` commits on success, rolls back on error, always closes.

    Services open one per operation, so a multi-step write (e.g. a link and all
    of its media) is atomic and a connection is never held between updates.
    """

    users: UserRepository
    links: LinkRepository
    channels: ChannelRepository
    settings: SettingsRepository
    broadcasts: BroadcastRepository
    stats: StatsRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> UnitOfWork:
        session = self._session = self._session_factory()
        self.users = UserRepository(session)
        self.links = LinkRepository(session)
        self.channels = ChannelRepository(session)
        self.settings = SettingsRepository(session)
        self.broadcasts = BroadcastRepository(session)
        self.stats = StatsRepository(session)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        assert self._session is not None
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None


UnitOfWorkFactory = Callable[[], UnitOfWork]
