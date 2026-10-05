"""PostgreSQL dumps using the same connection configuration as SQLAlchemy."""

import asyncio
import os
import logging
import tempfile
import gzip
import json
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from core.database import database_url
from core.database import get_engine
from core.maintenance import get_gate
from core.models import Base
from core.serialization import encode_row
from decouple import config
from sqlalchemy import select, text
from services.pg_tools import find_pg_tool, communicate

LOGGER = logging.getLogger(__name__)


def backup_directory() -> Path:
    directory = Path(config("BACKUP_DIR", default="backup")).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def export_data(connection, path: Path) -> None:
    """Stream a consistent, portable, data-only snapshot without loading all rows."""
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as output:
        output.write(
            json.dumps(
                {
                    "format": "cutly-data",
                    "version": 2,
                    "tables": list(Base.metadata.tables),
                }
            )
            + "\n"
        )
        digest, counts = hashlib.sha256(), {}
        for table in Base.metadata.sorted_tables:
            counts[table.name] = 0
            result = await connection.stream(select(table).order_by(table.c.id))
            async for rows in result.mappings().partitions(500):
                chunk = "".join(
                    json.dumps(
                        {"table": table.name, "row": encode_row(row)},
                        ensure_ascii=False,
                    )
                    + "\n"
                    for row in rows
                )
                digest.update(chunk.encode("utf-8"))
                counts[table.name] += len(rows)
                await asyncio.to_thread(output.write, chunk)
        output.write(
            json.dumps({"end": True, "counts": counts, "sha256": digest.hexdigest()})
            + "\n"
        )


async def create_data_backup() -> str:
    path = (
        backup_directory()
        / f"data-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.jsonl.gz"
    )
    try:
        async with get_gate().operation():
            async with get_engine().connect() as connection:
                if connection.dialect.name == "postgresql":
                    connection = await connection.execution_options(
                        isolation_level="REPEATABLE READ"
                    )
                async with connection.begin():
                    if connection.dialect.name == "sqlite":
                        await connection.execute(text("BEGIN"))
                    await export_data(connection, path)
        return str(path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def create_backup() -> str | None:
    url = database_url()
    if url.get_backend_name() != "postgresql":
        return None
    path = (
        backup_directory()
        / f"full-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.sql"
    )
    env = os.environ.copy()
    env["PGPASSWORD"] = url.password or ""
    try:
        process = await asyncio.create_subprocess_exec(
            await find_pg_tool("pg_dump"),
            "-U",
            url.username or "",
            "-h",
            url.host or "localhost",
            "-p",
            str(url.port or 5432),
            "-f",
            str(path),
            url.database or "",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await communicate(process)
        if process.returncode == 0:
            return str(path)
        LOGGER.error(
            "pg_dump failed (exit %s); verify client/server compatibility",
            process.returncode,
        )
    except (OSError, asyncio.TimeoutError):
        pass
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    path.unlink(missing_ok=True)
    return None
