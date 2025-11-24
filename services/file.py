"""File management services."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.models import File


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

    return await File.create(**data)


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
    file = await File.filter(code=code, owner_id=userid).first()
    
    if not file:
        return False
    
    # If part of an album, delete all files in the album
    if file.album_id:
        deleted_count = await File.filter(
            album_id=file.album_id,
            owner_id=userid
        ).delete()
    else:
        deleted_count = await File.filter(code=code, owner_id=userid).delete()
    
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

    queryset = File.all()
    if code is not None:
        queryset = queryset.filter(code=code)
    if userid is not None:
        queryset = queryset.filter(owner_id=userid)
    return await queryset


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

    queryset = File.filter(code=code)
    if userid is not None:
        queryset = queryset.filter(owner_id=userid)
    return await queryset.first()

