"""File persistence and atomic download counters."""

from sqlalchemy import update, select, delete
from core.cache import get_cache
from sqlalchemy.orm import joinedload
from core.database import session_scope
from core.models import File
from services.repository import BaseRepository


class FileRepository(BaseRepository[File]):
    def __init__(self):
        super().__init__(File)

    async def update(self, id, data):
        result = await super().update(id, data)
        if result:
            await self.invalidate_metadata(result.code, result.album_id)
        return result

    async def invalidate_metadata(self, code, album_id):
        await get_cache().invalidate_scope(f"file:{code}")
        if album_id:
            await get_cache().invalidate_scope(f"album:{album_id}")

    async def update_where(self, data, *conditions):
        if set(data) == {"count"}:
            return await super().update_where(data, *conditions)
        async with session_scope() as session:
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
        for code, album_id in rows:
            await self.invalidate_metadata(code, album_id)
        return len(rows)

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
        for code, album_id in rows:
            await self.invalidate_metadata(code, album_id)
        return bool(rows)

    async def create(self, data):
        result = await super().create(data)
        if result.album_id:
            await get_cache().invalidate_scope(f"album:{result.album_id}")
        return result

    async def counts_by_code(self, codes):
        async with session_scope() as session:
            return dict(
                (
                    await session.execute(
                        select(File.code, File.count).where(File.code.in_(codes))
                    )
                ).all()
            )

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
        async with session_scope() as session:
            rows = await session.execute(
                update(File)
                .where(File.id.in_([file.id for file in files]))
                .values(count=File.count + 1)
                .returning(File.id, File.count)
            )
            counts = dict(rows.all())
        for file in files:
            if file.id in counts:
                file.count = counts[file.id]
