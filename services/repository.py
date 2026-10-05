"""SQLAlchemy repositories with sessions scoped to each operation."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from core.database import session_scope
from core.models import Base

T = TypeVar("T", bound=Base)


class BaseRepository(ABC, Generic[T]):
    def __init__(self, model: type[T]) -> None:
        self.model = model

    async def first(self, *conditions, options=()) -> T | None:
        async with session_scope() as session:
            return await session.scalar(
                select(self.model).where(*conditions).options(*options).limit(1)
            )

    async def list(
        self, *conditions, order_by=(), limit=None, offset=0, options=()
    ) -> list[T]:
        stmt = (
            select(self.model).where(*conditions).options(*options).order_by(*order_by)
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with session_scope() as session:
            return list((await session.scalars(stmt)).all())

    async def get_by_id(self, id: int) -> T | None:
        return await self.first(self.model.id == id)

    async def get_all(self) -> list[T]:
        return await self.list()

    async def create(self, data: dict[str, Any]) -> T:
        async with session_scope() as session:
            instance = self.model(**data)
            session.add(instance)
            await session.flush()
            return instance

    async def get_or_create(self, defaults=None, **keys) -> tuple[T, bool]:
        conditions = [getattr(self.model, key) == value for key, value in keys.items()]
        existing = await self.first(*conditions)
        if existing is not None:
            return existing, False
        try:
            return await self.create({**(defaults or {}), **keys}), True
        except IntegrityError:
            existing = await self.first(*conditions)
            if existing is None:
                raise
            return existing, False

    async def update(self, id: int, data: dict[str, Any]) -> T | None:
        async with session_scope() as session:
            instance = await session.get(self.model, id)
            if instance is None:
                return None
            for key, value in data.items():
                setattr(instance, key, value)
            await session.flush()
            return instance

    async def update_where(self, data, *conditions) -> int:
        async with session_scope() as session:
            result = await session.execute(
                update(self.model).where(*conditions).values(**data)
            )
            return result.rowcount

    async def delete_where(self, *conditions) -> bool:
        async with session_scope() as session:
            result = await session.execute(delete(self.model).where(*conditions))
            return bool(result.rowcount)

    async def delete(self, id: int) -> bool:
        return await self.delete_where(self.model.id == id)

    async def exists(self, **filters) -> bool:
        return (
            await self.first(
                *(getattr(self.model, key) == value for key, value in filters.items())
            )
            is not None
        )

    async def count(self, **filters) -> int:
        async with session_scope() as session:
            return (
                await session.scalar(
                    select(func.count())
                    .select_from(self.model)
                    .where(
                        *(
                            getattr(self.model, key) == value
                            for key, value in filters.items()
                        )
                    )
                )
                or 0
            )

    @abstractmethod
    async def get_filtered(self, **filters) -> list[T]:
        raise NotImplementedError
