"""Restore a data snapshot written by :mod:`services.backup` (any version).

Two steps, both run by the Celery worker:

1. :meth:`RestoreService.stage` loads the file into a throw-away SQLite database
   created at the *backup's own* schema revision, then runs the normal Alembic
   migrations up to ``head``. Every constraint is checked there, and old backups
   are converted by exactly the same code that upgrades a live database — there
   is no second, hand-written converter to keep in sync. The current data is not
   touched; the admin sees the row counts and confirms.
2. :meth:`RestoreService.apply` replaces all application rows with the staged
   ones inside a single transaction: it either fully succeeds or changes nothing.

Raw ``pg_dump`` files are not parsed here on purpose: replaying arbitrary SQL is
``psql``/``pg_restore``'s job, and a full dump can always be restored with them.
"""
from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import json
import uuid
import zlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, delete, event, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DataError, IntegrityError

from core.clock import as_utc
from db.base import Base
from db.engine import Database
from db.migrations import upgrade
from repositories.redis.restores import StagedRestore
from services.backup import DATA_FORMAT

LEGACY_REVISION = "0001_sqlalchemy"  # versions 1 and 2 were written at this schema
SUPPORTED_VERSIONS = {1, 2, 3}
IGNORED_TABLES = {"alembic_version"}
_MAX_LINE = 64 * 1024 * 1024
_BATCH = 1000


class RestoreError(ValueError):
    """A user-facing (Persian) reason why a file cannot be restored."""


class RestoreService:
    def __init__(self, database: Database, directory: Path, *, max_bytes: int) -> None:
        self._database = database
        self._directory = directory
        self._max_bytes = max_bytes

    # ---- step 1: validate into a staging database (synchronous, worker only) ----
    def stage(self, upload: Path) -> StagedRestore:
        self._directory.mkdir(parents=True, exist_ok=True)
        staging = (self._directory / f"staging-{uuid.uuid4().hex}.sqlite3").resolve()
        engine = create_engine(f"sqlite:///{staging}")
        event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
        try:
            version, counts = self._build_staging(engine, upload)
        except BaseException:
            engine.dispose()  # release the file first (Windows cannot delete an open file)
            staging.unlink(missing_ok=True)
            raise
        engine.dispose()
        return StagedRestore(staging_path=str(staging), source_version=version, counts=counts)

    def _build_staging(self, engine, upload: Path) -> tuple[int, dict[str, int]]:
        try:
            with gzip.open(upload, "rt", encoding="utf-8") as source, engine.begin() as connection:
                header = self._read_header(source)
                upgrade(connection, header.get("revision") or LEGACY_REVISION)
                self._load_rows(connection, source, strict_end=header["version"] >= 2)
                upgrade(connection, "head")
                counts = {
                    table.name: connection.scalar(select(func.count()).select_from(table))
                    for table in Base.metadata.sorted_tables
                }
        except RestoreError:
            raise
        except (EOFError, zlib.error, gzip.BadGzipFile, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RestoreError("فایل فشرده یا متن آن خراب است.") from error
        except (IntegrityError, DataError, TypeError, ValueError, KeyError, AttributeError, binascii.Error) as error:
            # Duplicate keys, missing parents, wrong value types: bad data, not a bug.
            raise RestoreError(f"داده‌های بک‌آپ با هم سازگار نیستند: {type(error).__name__}") from error
        return header["version"], counts

    def _read_header(self, source) -> dict:
        try:
            header = json.loads(source.readline(_MAX_LINE))
        except json.JSONDecodeError as error:
            raise RestoreError("این فایل بک‌آپ دادهٔ ربات نیست.") from error
        if not isinstance(header, dict) or header.get("format") != DATA_FORMAT:
            raise RestoreError("این فایل بک‌آپ دادهٔ ربات نیست.")
        if header.get("version") not in SUPPORTED_VERSIONS:
            raise RestoreError(f"نسخهٔ بک‌آپ پشتیبانی نمی‌شود: {header.get('version')}")
        return header

    def _load_rows(self, connection: Connection, source, *, strict_end: bool) -> None:
        metadata = MetaData()
        metadata.reflect(connection)
        digest, counts, total_bytes = hashlib.sha256(), defaultdict(int), 0
        pending: dict[str, list[dict]] = defaultdict(list)
        footer = None
        while line := source.readline(_MAX_LINE):
            total_bytes += len(line)
            if total_bytes > self._max_bytes:
                raise RestoreError("حجم بک‌آپ بیش از حد مجاز است.")
            if not line.endswith("\n"):
                raise RestoreError("فایل بک‌آپ ناقص است.")
            record = json.loads(line)
            if record.get("end"):
                footer = record
                break
            name = record.get("table")
            if name in IGNORED_TABLES:
                continue
            if name not in metadata.tables:
                raise RestoreError(f"جدول ناشناخته در بک‌آپ: {name}")
            table = metadata.tables[name]
            pending[name].append(self._decode_row(table, record.get("row") or {}))
            digest.update(line.encode("utf-8"))
            counts[name] += 1
            if len(pending[name]) >= _BATCH:
                connection.execute(table.insert(), pending.pop(name))
        # Header order is parents-first, but a batch may still be pending for an
        # earlier table: flush in metadata (dependency) order.
        for table in metadata.sorted_tables:
            if pending.get(table.name):
                connection.execute(table.insert(), pending.pop(table.name))
        if footer is None:
            if strict_end:
                raise RestoreError("فایل بک‌آپ ناقص است (پایان فایل یافت نشد).")
            return
        expected = {name: count for name, count in footer.get("counts", {}).items() if name not in IGNORED_TABLES}
        if expected != {name: counts.get(name, 0) for name in expected} or footer.get("sha256") not in (
            None, digest.hexdigest()
        ):
            raise RestoreError("checksum بک‌آپ معتبر نیست؛ فایل تغییر کرده یا ناقص است.")

    @staticmethod
    def _decode_row(table: Table, row: dict) -> dict:
        unknown = row.keys() - table.columns.keys()
        if unknown:
            raise RestoreError(f"ستون ناشناخته در {table.name}: {', '.join(sorted(unknown))}")
        decoded = {}
        for name, value in row.items():
            try:
                kind = table.columns[name].type.python_type
            except NotImplementedError:
                kind = object
            if value is not None and kind is bytes and isinstance(value, dict):
                value = base64.b64decode(value["$bytes"], validate=True)
            elif value is not None and kind is datetime and isinstance(value, str):
                value = as_utc(datetime.fromisoformat(value))
            decoded[name] = value
        return decoded

    # ---- step 2: replace live data (async, worker only) ----
    async def apply(self, staged: StagedRestore) -> dict[str, int]:
        staging = create_engine(f"sqlite:///{staged.staging_path}")
        tables = Base.metadata.sorted_tables
        try:
            with staging.connect() as source:
                async with self._database.engine.begin() as target:
                    for table in reversed(tables):
                        await target.execute(delete(table))
                    for table in tables:
                        result = source.execution_options(stream_results=True).execute(select(table))
                        for rows in result.mappings().partitions(_BATCH):
                            await target.execute(table.insert(), [dict(row) for row in rows])
                    if target.dialect.name == "postgresql":
                        await _reset_sequences(target, tables)
        finally:
            staging.dispose()
        return dict(staged.counts)


async def _reset_sequences(connection, tables: list[Table]) -> None:
    """Explicit ids were inserted; move each serial sequence past the maximum."""
    for table in tables:
        column = table.autoincrement_column
        if column is None:
            continue
        await connection.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{column.name}'), "
            f"COALESCE(MAX({column.name}), 1), MAX({column.name}) IS NOT NULL) FROM {table.name}"
        ))
