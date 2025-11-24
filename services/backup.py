"""Backup services for database export."""

from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
from typing import Optional

from app.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_USER


async def create_backup() -> Optional[str]:
    """Create a PostgreSQL dump asynchronously.

    Examples:
        >>> path = await create_backup()
        >>> bool(path) if path else False
        True

    Returns:
        Absolute path to the dump file or ``None`` when the command fails.
        
    Raises:
        OSError: If the subprocess cannot be created.
    """

    if not DB_NAME or not DB_USER:
        return None

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    file_name = f"backup-{timestamp}.sql"
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD
    command = f"pg_dump -U {DB_USER} -h {DB_HOST} {DB_NAME} > {file_name}"
    
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.wait()
        if process.returncode == 0:
            return str(Path(__file__).parent.parent.joinpath(file_name))
    except Exception:  # noqa: BLE001
        pass
    
    return None

