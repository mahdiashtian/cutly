"""Backups: a full ``pg_dump`` and a portable, data-only ``.jsonl.gz`` snapshot.

Both run inside the Celery worker, never in the bot process, because they read
the whole database. The data format is line-delimited JSON so it can be written
and read in a stream with constant memory:

    {"format": "cutly-data", "version": 3, "revision": "<alembic rev>", "tables": [...]}
    {"table": "users", "row": {...}}            one line per row, parents first
    {"end": true, "counts": {...}, "sha256": "<hash of every row line>"}

Versions 1 and 2 were written by the previous release (old schema, no revision).
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from core.clock import utcnow
from db.base import Base
from db.engine import Database
from db.migrations import head_revision

log = logging.getLogger(__name__)

DATA_FORMAT = "cutly-data"
DATA_VERSION = 3
_PARTITION = 500


def encode_value(value):
    """JSON-safe, lossless: bytes as base64, datetimes as ISO-8601."""
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class BackupService:
    def __init__(self, database: Database, directory: Path, *, pg_dump_path: str = "",
                 pg_tool_timeout: int = 900) -> None:
        self._database = database
        self._directory = directory
        self._pg_dump_path = pg_dump_path
        self._pg_tool_timeout = pg_tool_timeout

    def new_path(self, prefix: str, suffix: str) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        return (self._directory / f"{prefix}-{utcnow():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}{suffix}").resolve()

    async def export_data(self, prefix: str = "data") -> Path:
        """Stream every table into a checksummed snapshot, from one transaction."""
        path = self.new_path(prefix, ".jsonl.gz")
        tables = Base.metadata.sorted_tables
        try:
            async with self._database.engine.connect() as connection:
                if connection.dialect.name == "postgresql":
                    # One consistent snapshot across all tables.
                    connection = await connection.execution_options(isolation_level="REPEATABLE READ")
                async with connection.begin():
                    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as output:
                        header = {"format": DATA_FORMAT, "version": DATA_VERSION,
                                  "revision": head_revision(), "tables": [t.name for t in tables]}
                        output.write(json.dumps(header) + "\n")
                        digest, counts = hashlib.sha256(), {}
                        for table in tables:
                            counts[table.name] = 0
                            result = await connection.stream(select(table).order_by(*table.primary_key.columns))
                            async for rows in result.mappings().partitions(_PARTITION):
                                for row in rows:
                                    line = json.dumps(
                                        {"table": table.name,
                                         "row": {key: encode_value(value) for key, value in row.items()}},
                                        ensure_ascii=False,
                                    ) + "\n"
                                    digest.update(line.encode("utf-8"))
                                    output.write(line)
                                counts[table.name] += len(rows)
                        output.write(json.dumps({"end": True, "counts": counts, "sha256": digest.hexdigest()}) + "\n")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    async def full_dump(self) -> Path | None:
        """``pg_dump`` of the whole database (schema + data); PostgreSQL only."""
        url = self._database.engine.url
        if url.get_backend_name() != "postgresql":
            return None
        path = self.new_path("full", ".sql")
        process = await asyncio.create_subprocess_exec(
            self._pg_dump_path or "pg_dump",
            "--no-password", "-h", url.host or "localhost", "-p", str(url.port or 5432),
            "-U", url.username or "", "-f", str(path), url.database or "",
            env={**os.environ, "PGPASSWORD": url.password or ""},
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), self._pg_tool_timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            path.unlink(missing_ok=True)
            raise
        if process.returncode != 0:
            log.error("pg_dump failed (exit %s): %s", process.returncode, stderr.decode(errors="replace")[-500:])
            path.unlink(missing_ok=True)
            return None
        return path
