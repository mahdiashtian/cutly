"""File persistence and atomic download counters."""

from sqlalchemy import update, select, delete
from core.cache import get_cache
from core.maintenance import database_operation
from sqlalchemy.orm import joinedload
from core.database import session_scope
from core.models import File
from services.repository import BaseRepository

# Leave room for scalar binds on SQLite builds with a 999-variable limit.
SQL_BATCH_SIZE = 900


class FileRepository(BaseRepository[File]):
    def __init__(self):
        super().__init__(File)

    @database_operation
    async def update(self, id, data):
        async with session_scope() as session:
            result = await session.get(File, id, with_for_update=True)
            if result is None:
                return None
            previous = (result.code, result.album_id)
            for key, value in data.items():
                setattr(result, key, value)
            await session.flush()
        await self.invalidate_rows([previous, (result.code, result.album_id)])
        return result

    async def invalidate_metadata(self, code, album_id):
        await self.invalidate_rows([(code, album_id)])

    async def invalidate_rows(self, rows):
        scopes = set()
        for code, album_id in rows:
            scopes.add(f"file:{code}")
            if album_id:
                scopes.add(f"album:{album_id}")
        await get_cache().invalidate_scopes(scopes)

    @database_operation
    async def update_where(self, data, *conditions):
        if set(data) == {"count"}:
            return await super().update_where(data, *conditions)
        async with session_scope() as session:
            previous = list(
                (
                    await session.execute(
                        select(File.code, File.album_id)
                        .where(*conditions)
                        .with_for_update()
                    )
                ).all()
            )
            rows = list(
                (
                    await session.execute(
                        update(File)
                        .where(*conditions)
                        .values(**data)
                        .returning(File.code, File.album_id)
                    )
                ).all()
            )
        await self.invalidate_rows([*previous, *rows])
        return len(rows)

    @database_operation
    async def delete_where(self, *conditions):
        async with session_scope() as session:
            rows = list(
                (
                    await session.execute(
                        delete(File)
                        .where(*conditions)
                        .returning(File.code, File.album_id)
                    )
                ).all()
            )
        await self.invalidate_rows(rows)
        return bool(rows)

    async def create(self, data):
        return (await self.create_many([data]))[0]

    @database_operation
    async def create_many(self, data):
        async with session_scope() as session:
            rows = [File(**values) for values in data]
            session.add_all(rows)
            await session.flush()
        await self.invalidate_rows([(row.code, row.album_id) for row in rows])
        return rows

    async def counts_by_code(self, codes):
        if not codes:
            return {}
        codes = list(set(codes))
        counts = {}
        async with session_scope() as session:
            for start in range(0, len(codes), SQL_BATCH_SIZE):
                rows = await session.execute(
                    select(File.code, File.count).where(
                        File.code.in_(codes[start : start + SQL_BATCH_SIZE])
                    )
                )
                counts.update(rows.all())
        return counts

    async def get_by_code(self, code, owner_id=None):
        conditions = [File.code == code]
        if owner_id is not None:
            conditions.append(File.owner_id == owner_id)
        return await self.first(*conditions, options=(joinedload(File.owner),))

    async def get_user_files(self, owner_id, limit=None, offset=0):
        return await self.list(
            File.owner_id == owner_id,
            order_by=(File.created_at.desc(),),
            limit=limit,
            offset=offset,
            options=(joinedload(File.owner),),
        )

    async def get_filtered(
        self, file_type=None, owner_id=None, has_password=None, **filters
    ):
        conditions = []
        if file_type:
            conditions.append(File.type == file_type)
        if owner_id is not None:
            conditions.append(File.owner_id == owner_id)
        if has_password is not None:
            conditions.append(
                File.password.is_not(None) if has_password else File.password.is_(None)
            )
        return await self.list(
            *conditions,
            order_by=(File.created_at.desc(),),
            options=(joinedload(File.owner),),
        )

    async def delete_by_code(self, code, owner_id):
        return await self.delete_where(File.code == code, File.owner_id == owner_id)

    async def increment_download_count(self, code):
        return bool(
            await self.update_where({"count": File.count + 1}, File.code == code)
        )

    async def get_popular_files(self, limit=10):
        return await self.list(
            order_by=(File.count.desc(),),
            limit=limit,
            options=(joinedload(File.owner),),
        )

    async def increment_files(self, files):
        if not files:
            return
        ids, counts = list({file.id for file in files}), {}
        async with session_scope() as session:
            for start in range(0, len(ids), SQL_BATCH_SIZE):
                rows = await session.execute(
                    update(File)
                    .where(File.id.in_(ids[start : start + SQL_BATCH_SIZE]))
                    .values(count=File.count + 1)
                    .returning(File.id, File.count)
                )
                counts.update(rows.all())
        for file in files:
            if file.id in counts:
                file.count = counts[file.id]
