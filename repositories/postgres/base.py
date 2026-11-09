"""Shared helpers for SQL repositories."""
from __future__ import annotations

from sqlalchemy import Table
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession


class SqlRepository:
    """A repository only runs statements on the Unit of Work's session; it never
    commits. The Unit of Work decides the transaction boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _insert(self, table: Table):
        """Dialect-specific INSERT, which supports ``ON CONFLICT`` on both backends."""
        if self._session.bind.dialect.name == "postgresql":
            return postgresql.insert(table)
        return sqlite.insert(table)
