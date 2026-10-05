"""File management services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from core.database import session_scope
from core.maintenance import get_gate

from core.models import File
from core.cache import get_cache
from core.serialization import encode_row, decode_row
from services.user import read_user_from_db
from services.file_repository import FileRepository

_repo = FileRepository()


async def create_file_from_db(data: Dict[str, Any]) -> File:
    """Persist a new file record.

    Args:
        data: File data dictionary including message_id, code, type, etc.

    Returns:
        Newly created File instance.

    Examples:
        >>> file = await create_file_from_db({
        ...     "type": "photo",
        ...     "code": "abc123",
        ...     "message_id": 12345,
        ...     "owner_id": 12345678,
        ...     "size": 1024,
        ...     "album_id": None,
        ...     "album_order": 0
        ... })
    """

    return await _repo.create(data)


async def delete_file_from_db(userid: int, code: str) -> bool:
    """Remove a file owned by a given user.

    If the file is part of an album, all files in the album are deleted.

    Args:
        userid: Owner's Telegram user ID.
        code: File unique code.

    Returns:
        True if file(s) were deleted, False otherwise.

    Examples:
        >>> deleted = await delete_file_from_db(12345678, "abc123")
        >>> if deleted:
        ...     print("File deleted successfully")
    """

    # First, find the file to check if it's part of an album
    file = await _repo.get_by_code(code, owner_id=userid)

    if not file:
        return False

    # If part of an album, delete all files in the album
    if file.album_id:
        deleted_count = await _repo.delete_where(
            File.album_id == file.album_id, File.owner_id == userid
        )
    else:
        deleted_count = await _repo.delete_by_code(code, userid)

    return deleted_count > 0


async def read_files_from_db(
    code: Optional[str] = None, userid: Optional[int] = None
) -> List[File]:
    """Fetch multiple file records filtered by optional parameters.

    Args:
        code: Optional file code filter.
        userid: Optional owner ID filter.

    Returns:
        List of matching File instances.

    Examples:
        >>> all_files = await read_files_from_db()
        >>> user_files = await read_files_from_db(userid=12345678)
        >>> specific_file = await read_files_from_db(code="abc123")
    """

    conditions = []
    if code is not None:
        conditions.append(File.code == code)
    if userid is not None:
        conditions.append(File.owner_id == userid)
    return await _repo.list(*conditions)


async def read_file_from_db(code: str, userid: Optional[int] = None) -> Optional[File]:
    """Fetch a single file record by code and optional owner.

    Args:
        code: File unique code.
        userid: Optional owner ID filter.

    Returns:
        File instance or None if not found.

    Examples:
        >>> file = await read_file_from_db("abc123")
        >>> user_file = await read_file_from_db("abc123", userid=12345678)
    """

    cache = get_cache()
    scope = f"file:{code}"
    data, version = await cache.get_snapshot(scope, "metadata")
    if data is not None:
        counts = await _repo.counts_by_code([code])
        if code not in counts:
            return None
        file = File(**decode_row(File.__table__, data), count=counts[code])
        if userid is not None and file.owner_id != userid:
            return None
        file.owner = await read_user_from_db(file.owner_id)
        return file
    file = await _repo.get_by_code(code, owner_id=userid)
    if file is not None:
        row = {
            column.name: getattr(file, column.name)
            for column in File.__table__.columns
            if column.name != "count"
        }
        await cache.set_snapshot(scope, "metadata", encode_row(row), version)
    return file


async def read_album_files(album_id: str) -> List[File]:
    cache = get_cache()
    scope = f"album:{album_id}"
    data, version = await cache.get_snapshot(scope, "members")
    if data is not None:
        counts = await _repo.counts_by_code([row["code"] for row in data])
        return [
            File(**decode_row(File.__table__, row), count=counts[row["code"]])
            for row in data
            if row["code"] in counts
        ]
    files = await _repo.list(
        File.album_id == album_id, order_by=(File.album_order, File.id)
    )
    rows = [
        encode_row(
            {
                column.name: getattr(file, column.name)
                for column in File.__table__.columns
                if column.name != "count"
            }
        )
        for file in files
    ]
    await cache.set_snapshot(scope, "members", rows, version)
    return files


async def save_file_fields(file: File, *fields: str) -> None:
    """Update only the changed fields of a detached conversation object."""
    await _repo.update(file.id, {name: getattr(file, name) for name in fields})


async def increment_file_downloads(files: List[File]) -> None:
    await _repo.increment_files(files)


class DownloadLimitError(ValueError):
    pass


async def reserve_file_downloads(files: List[File]) -> dict[str, int]:
    """Reserve slots atomically, including concurrent requests for one link."""
    codes = {file.code for file in files}
    if not codes:
        raise DownloadLimitError("No media in album")
    gate = get_gate()
    async with gate.download_lock:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        File.code,
                        File.count,
                        File.max_downloads,
                        File.expires_at,
                    ).where(File.code.in_(codes))
                )
            ).all()
        now = datetime.now(timezone.utc)
        if len(rows) != len(codes) or any(
            (row.expires_at is not None and row.expires_at <= now)
            or (
                row.max_downloads is not None
                and row.count + gate.downloads.get(row.code, 0) >= row.max_downloads
            )
            for row in rows
        ):
            raise DownloadLimitError("Expired, exhausted or deleted file")
        for row in rows:
            gate.downloads[row.code] = gate.downloads.get(row.code, 0) + 1
        # Pending deliveries never become permanent counters or enter backups.
        return {row.code: row.count + 1 for row in rows}


async def finish_file_downloads(files: List[File], *, success: bool) -> None:
    gate = get_gate()
    async with gate.download_lock:
        try:
            if success:
                await _repo.increment_files(files)
        finally:
            for code in {file.code for file in files}:
                remaining = gate.downloads.get(code, 0) - 1
                if remaining > 0:
                    gate.downloads[code] = remaining
                else:
                    gate.downloads.pop(code, None)


def file_access_error(file: File) -> Optional[str]:
    """Return a Persian reason when a file link may no longer be downloaded."""
    if file.expires_at:
        expires_at = file.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            return "⏰ زمان اعتبار این لینک به پایان رسیده است."
    if file.max_downloads is not None and file.count >= file.max_downloads:
        return "🚫 سقف دانلود این لینک پر شده است."
    return None
