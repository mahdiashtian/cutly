"""Import logical snapshots into the current schema, without executing dump SQL.

Schema DDL, roles, ACLs and server settings are intentionally not replayed. This
lets application data move across PostgreSQL majors and from legacy ORM schemas.
Unknown data/columns and unsupported literals fail before any database change.
"""

from __future__ import annotations

import asyncio
import io
import threading
from core.concurrency import run_blocking
import base64
import gzip
import hashlib
import json
import logging
import re
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from decouple import config
from sqlalchemy import delete, insert, select, text
from core.cache import get_cache
from core.database import get_engine
from core.maintenance import get_gate
from core.models import Base
from core.serialization import decode_row, encode_row, parse_timestamp
from services.backup import backup_directory, export_data
from services.pg_tools import find_pg_tool

LOGGER = logging.getLogger(__name__)
IGNORED_TABLES = {"alembic_version", "aerich"}
IDENTIFIER = (
    r'(?:"(?:[^"\n]|"")+"|[A-Za-z_][\w$]*)(?:\.(?:"(?:[^"\n]|"")+"|[A-Za-z_][\w$]*))?'
)
COPY = re.compile(
    rf"^COPY\s+({IDENTIFIER})\s*\((.*?)\)\s+FROM\s+stdin\s*;$", re.I | re.S
)
INSERT = re.compile(
    rf"^INSERT\s+INTO\s+({IDENTIFIER})\s*(?:\((.*?)\))?\s+VALUES\s+(.*);$", re.I | re.S
)


class RestoreError(ValueError):
    pass


@dataclass
class PreparedRestore:
    spool: Path
    counts: dict[str, int]
    source_version: str | None
    source_format: str
    digest: str

    def close(self):
        self.spool.unlink(missing_ok=True)


@dataclass
class RestoreResult:
    counts: dict[str, int]
    safety_backup: str


def _identifier(value):
    parts = re.findall(r'"((?:[^"]|"")+)"|([\w$]+)', value)
    names = [
        quoted.replace('""', '"') if quoted else bare.lower() for quoted, bare in parts
    ]
    if len(names) == 2 and names[0] != "public":
        raise RestoreError("فقط schema عمومی public پشتیبانی می‌شود.")
    return names[-1]


def _columns(value):
    return [_identifier(item.strip()) for item in value.split(",")]


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _unescape(value):
    # PostgreSQL COPY text escapes, including octal byte sequences.
    def replace(match):
        escape = match.group(1)
        mapping = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
        if escape in mapping:
            return mapping[escape]
        if re.fullmatch(r"[0-7]{1,3}", escape):
            return chr(int(escape, 8))
        if escape.startswith("x") and len(escape) > 1:
            return chr(int(escape[1:], 16))
        return escape

    return re.sub(r"\\([0-7]{1,3}|x[0-9a-fA-F]{1,2}|.)", replace, value)


def _sql_values(value, standard_strings=True):
    """Only literal VALUES tuples; functions/subqueries are never evaluated."""
    token = re.compile(
        r"\s*(?:((?:E'(?:[^'\\]|\\.|'')*')|(?:'(?:[^']|'')*'))|([-+]?\d+(?:\.\d+)?)|(NULL|TRUE|FALSE)|([(),]))",
        re.I | re.S,
    )
    position, rows, row, expecting_value = 0, [], None, True
    while position < len(value):
        if not value[position:].strip():
            break
        match = token.match(value, position)
        if not match:
            raise RestoreError(
                "INSERT شامل عبارت غیر literal یا cast پشتیبانی‌نشده است."
            )
        position = match.end()
        string, number, keyword, punctuation = match.groups()
        if punctuation == "(":
            if row is not None:
                raise RestoreError("INSERT نامعتبر است.")
            row, expecting_value = [], True
        elif punctuation == ")":
            if row is None or expecting_value:
                raise RestoreError("INSERT نامعتبر است.")
            rows.append(row)
            row = None
        elif punctuation == ",":
            if row is not None:
                if expecting_value:
                    raise RestoreError("INSERT نامعتبر است.")
                expecting_value = True
        else:
            if row is None or not expecting_value:
                raise RestoreError("INSERT نامعتبر است.")
            if string:
                escaped = string[0].upper() == "E"
                item = string[2:-1] if escaped else string[1:-1]
                item = item.replace("''", "'")
                item = _unescape(item) if escaped or not standard_strings else item
            elif number:
                item = int(number) if "." not in number else float(number)
            else:
                item = None if keyword.upper() == "NULL" else keyword.upper() == "TRUE"
            row.append(item)
            expecting_value = False
    if row is not None or not rows:
        raise RestoreError("INSERT ناقص است.")
    return rows


def _known_column_order(name, length):
    if name in IGNORED_TABLES:
        return [f"ignored_{index}" for index in range(length)]
    if name not in Base.metadata.tables:
        raise RestoreError(f"جدول ناشناخته: {name}")
    current = list(Base.metadata.tables[name].columns.keys())
    variants = [current]
    if name == "user":
        variants.append([key for key in current if key != "last_activity_at"])
    if name == "file":
        variants.append(
            [key for key in current if key not in {"expires_at", "max_downloads"}]
        )
    for columns in variants:
        if len(columns) == length:
            return columns
    raise RestoreError(
        "ترتیب ستون‌های INSERT قابل تشخیص نیست؛ بک‌آپ را با --column-inserts یا COPY بسازید."
    )


def _normalize(table_name, row):
    table = Base.metadata.tables[table_name]
    unknown = row.keys() - set(table.columns.keys())
    if unknown:
        raise RestoreError(
            f"ستون ناشناخته در {table_name}: {', '.join(sorted(unknown))}"
        )
    result = {}
    for column in table.columns:
        value = row.get(column.name)
        if column.name not in row:
            if column.default is not None:
                value = column.default.arg
                if callable(value):
                    # Missing creation timestamps in a data snapshot are not safe.
                    raise RestoreError(
                        f"ستون الزامی {table_name}.{column.name} در بک‌آپ موجود نیست."
                    )
            elif not column.nullable:
                raise RestoreError(
                    f"ستون الزامی {table_name}.{column.name} موجود نیست."
                )
        if value is None:
            if not column.nullable:
                raise RestoreError(
                    f"مقدار خالی برای {table_name}.{column.name} مجاز نیست."
                )
            result[column.name] = None
            continue
        kind = column.type.python_type
        try:
            if kind is bytes:
                if isinstance(value, dict):
                    value = base64.b64decode(value["$bytes"], validate=True)
                elif isinstance(value, str) and value.startswith("\\x"):
                    value = bytes.fromhex(value[2:])
                elif isinstance(value, str):
                    # Old bytea escape format: escaped octal bytes/backslashes.
                    value = _unescape(value).encode("latin1")
                else:
                    raise ValueError("invalid bytea")
            elif kind is datetime:
                value = parse_timestamp(value)
                value = (
                    value.replace(tzinfo=timezone.utc)
                    if value.tzinfo is None
                    else value.astimezone(timezone.utc)
                )
            elif kind is bool:
                if str(value).lower() not in {"true", "false", "t", "f", "0", "1"}:
                    raise ValueError("invalid boolean")
                value = str(value).lower() in {"true", "t", "1"}
            elif kind is int:
                if isinstance(value, bool) or (
                    isinstance(value, float) and not value.is_integer()
                ):
                    raise ValueError("invalid integer")
                value = int(value)
                limit = (
                    2**63 if column.type.__class__.__name__ == "BigInteger" else 2**31
                )
                if not -limit <= value < limit:
                    raise ValueError("integer overflow")
            else:
                if not isinstance(value, str):
                    raise ValueError("invalid text")
                if "\0" in value or (
                    getattr(column.type, "length", None)
                    and len(value) > column.type.length
                ):
                    raise ValueError("text length/encoding")
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise RestoreError(
                f"مقدار نامعتبر برای {table_name}.{column.name}"
            ) from error
        result[column.name] = value
    return encode_row(result)


class _BoundedReader:
    def __init__(self, stream, stop=None):
        self.stream = stream
        self.stop = stop
        self.total = 0
        self.limit = config("RESTORE_MAX_BYTES", default=2 * 1024**3, cast=int)

    def __iter__(self):
        return self

    def __next__(self):
        if self.stop is not None and self.stop.is_set():
            raise RestoreError("بازیابی لغو شد.")
        line = self.stream.readline(16 * 1024**2 + 1)
        if not line:
            raise StopIteration
        self.total += len(line.encode("utf-8"))
        if len(line) > 16 * 1024**2 or self.total > self.limit:
            raise RestoreError("حجم بازشدهٔ بک‌آپ از محدودیت مجاز بیشتر است.")
        return line


class _SQLBuffer:
    """Linear-memory statement accumulation; no per-line rescanning."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.buffer = io.StringIO()
        self.size = 0
        self.nonspace = False
        self.last = ""

    def __bool__(self):
        return bool(self.size)

    def append(self, value):
        self.size += len(value)
        if self.size > 32 * 1024**2:
            raise RestoreError("یک دستور SQL بیش از حد بزرگ است؛ از COPY استفاده کنید.")
        self.buffer.write(value)
        self.nonspace = self.nonspace or bool(value.strip())
        self.last = value[-1:] or self.last

    def value(self):
        return self.buffer.getvalue()


def _parse(path: Path, spool: Path, source_format: str, stop=None) -> PreparedRestore:
    counts, version, tables_seen = Counter(), None, set()
    db = sqlite3.connect(spool)
    if stop is not None:
        db.set_progress_handler(lambda: int(stop.is_set()), 10000)
    db.execute("CREATE TABLE rows (table_name TEXT, payload TEXT)")
    db.execute("CREATE INDEX ix_rows_table ON rows(table_name)")
    db.execute(
        "CREATE TABLE identities (table_name TEXT, name TEXT, value TEXT, UNIQUE(table_name,name,value))"
    )
    db.execute("CREATE TABLE owners (id INTEGER PRIMARY KEY, userid INTEGER UNIQUE)")
    owner_column = None

    def add(table_name, columns, values):
        table_name = _identifier(table_name)
        if table_name in IGNORED_TABLES:
            return
        if table_name not in Base.metadata.tables:
            raise RestoreError(
                f"جدول ناشناخته: {table_name}؛ بازیابی بدون حذف دادهٔ ناشناخته متوقف شد."
            )
        tables_seen.add(table_name)
        unknown = set(columns) - set(Base.metadata.tables[table_name].columns.keys())
        if unknown:
            raise RestoreError(
                f"ستون ناشناخته در {table_name}: {', '.join(sorted(unknown))}"
            )
        if values is None:
            return
        if len(columns) != len(values) or len(columns) != len(set(columns)):
            raise RestoreError("تعداد ستون‌ها و مقادیر یکسان نیست.")
        row = _normalize(table_name, dict(zip(columns, values)))
        try:
            for name in (
                "id",
                {"user": "userid", "file": "code", "channel": "channel_id"}.get(
                    table_name
                ),
            ):
                if name:
                    db.execute(
                        "INSERT INTO identities VALUES (?,?,?)",
                        (table_name, name, str(row[name])),
                    )
        except sqlite3.IntegrityError as error:
            raise RestoreError(f"مقدار تکراری کلید در {table_name}") from error
        db.execute(
            "INSERT INTO rows VALUES (?,?)",
            (table_name, json.dumps(row, ensure_ascii=False)),
        )
        if table_name == "user":
            db.execute("INSERT INTO owners VALUES (?,?)", (row["id"], row["userid"]))
        counts[table_name] += 1

    try:
        with path.open("rb") as raw:
            compressed = raw.read(2) == b"\x1f\x8b"
        opener = gzip.open if compressed else open
        with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
            lines = _BoundedReader(stream, stop)
            first = next(lines, "")
            if first.lstrip().startswith("{"):
                header = json.loads(first)
                if header.get("format") != "cutly-data" or header.get(
                    "version"
                ) not in {1, 2}:
                    raise RestoreError("نسخه یا قالب بک‌آپ داده پشتیبانی نمی‌شود.")
                if set(header.get("tables", [])) != set(Base.metadata.tables):
                    raise RestoreError("فهرست جدول‌های بک‌آپ داده کامل نیست.")
                tables_seen.update(header["tables"])
                source_format = "cutly-data"
                owner_column = "userid"
                digest, finished = hashlib.sha256(), False
                for line in lines:
                    entry = json.loads(line)
                    if finished:
                        raise RestoreError("دادهٔ اضافی پس از پایان بک‌آپ وجود دارد.")
                    if entry.get("end") is True:
                        if entry.get("sha256") != digest.hexdigest() or entry.get(
                            "counts"
                        ) != {name: counts[name] for name in Base.metadata.tables}:
                            raise RestoreError(
                                "checksum یا تعداد رکوردهای بک‌آپ صحیح نیست."
                            )
                        finished = True
                        continue
                    digest.update(line.encode("utf-8"))
                    add(entry["table"], list(entry["row"]), list(entry["row"].values()))
                if header["version"] == 2 and not finished:
                    raise RestoreError("بک‌آپ داده ناقص است.")
            else:
                statement, quoted, dollar, block_comment = _SQLBuffer(), False, None, False
                escaped_string, standard_strings = False, True
                postgres_dump, dump_complete = False, False
                create_columns = {}
                copy_target = None
                for line in _chain(first, lines):
                    if not quoted and not dollar and not copy_target:
                        postgres_dump |= line.strip() == "-- PostgreSQL database dump"
                        dump_complete |= (
                            line.strip() == "-- PostgreSQL database dump complete"
                        )
                    found = re.search(
                        r"Dumped (?:from database|by pg_dump) version ([\w.]+)", line
                    )
                    if found and version is None:
                        version = found[1]
                    # --inserts emits no SQL for an empty table; pg_dump's
                    # TABLE DATA header still identifies the complete snapshot.
                    header = re.match(
                        r"-- Data for Name: (\w+); Type: TABLE DATA; Schema: public;",
                        line,
                    )
                    if header and not quoted and not dollar and not copy_target:
                        add(header[1], [], None)
                    if copy_target:
                        if line.rstrip("\r\n") == "\\.":
                            copy_target = None
                            continue
                        values = [
                            None if item == r"\N" else _unescape(item)
                            for item in line.rstrip("\r\n").split("\t")
                        ]
                        add(*copy_target, values)
                        continue
                    if not statement and line.lstrip().startswith("\\"):
                        if not re.match(r"\\(?:un)?restrict\s+\w+\s*$", line.strip()):
                            raise RestoreError("دستور psql در بک‌آپ پشتیبانی نمی‌شود.")
                        continue
                    i = 0
                    while i < len(line):
                        if block_comment:
                            end = line.find("*/", i)
                            if end < 0:
                                break
                            block_comment, i = False, end + 2
                            continue
                        if dollar:
                            end = line.find(dollar, i)
                            if end < 0:
                                statement.append(line[i:])
                                break
                            statement.append(line[i : end + len(dollar)])
                            i, dollar = end + len(dollar), None
                            continue
                        char = line[i]
                        if (
                            quoted
                            and escaped_string
                            and char == "\\"
                            and i + 1 < len(line)
                        ):
                            statement.append(line[i : i + 2])
                            i += 2
                            continue
                        if not quoted and line[i : i + 2] == "--":
                            break
                        if not quoted and line[i : i + 2] == "/*":
                            block_comment, i = True, i + 2
                            continue
                        if not quoted and char == "$":
                            match = re.match(r"\$(?:[A-Za-z_]\w*)?\$", line[i:])
                            if match:
                                dollar = match[0]
                                statement.append(dollar)
                                i += len(dollar)
                                continue
                        if char == "'":
                            if quoted and line[i : i + 2] == "''":
                                statement.append("''")
                                i += 2
                                continue
                            if not quoted:
                                escaped_string = not standard_strings or bool(
                                    statement and statement.last.upper() == "E"
                                )
                            quoted = not quoted
                        statement.append(char)
                        i += 1
                        if char != ";" or quoted:
                            continue
                        sql = statement.value().strip()
                        statement.clear()
                        if re.match(
                            r'^(?:ALTER TABLE(?: ONLY)?\s+(?:public\.)?"?file"?|CREATE TABLE\s+(?:public\.)?"?file"?)\b',
                            sql,
                            re.I,
                        ):
                            foreign_key = re.search(
                                r'FOREIGN KEY\s*\("?owner_id"?\)\s*REFERENCES\s+(?:public\.)?"?user"?\s*\("?(id|userid)"?\)',
                                sql,
                                re.I,
                            )
                            inline_key = re.search(
                                r'"?owner_id"?\s+\w+.*?REFERENCES\s+(?:public\.)?"?user"?\s*\("?(id|userid)"?\)',
                                sql,
                                re.I,
                            )
                            if foreign_key or inline_key:
                                owner_column = (foreign_key or inline_key)[1].lower()
                        match = COPY.match(sql)
                        if match:
                            copy_target = (match[1], _columns(match[2]))
                            add(*copy_target, None)
                        elif sql.upper().startswith("COPY"):
                            raise RestoreError(
                                "فقط COPY متنی FROM stdin پشتیبانی می‌شود."
                            )
                        elif match := INSERT.match(sql):
                            name = _identifier(match[1])
                            columns = (
                                _columns(match[2])
                                if match[2]
                                else create_columns.get(name)
                            )
                            for values in _sql_values(match[3], standard_strings):
                                columns = columns or _known_column_order(
                                    name, len(values)
                                )
                                add(match[1], columns, values)
                        elif sql.upper().startswith("INSERT"):
                            raise RestoreError("INSERT غیر literal پشتیبانی نمی‌شود.")
                        elif match := re.match(
                            rf"CREATE TABLE\s+({IDENTIFIER})\s*\((.*)\);$",
                            sql,
                            re.I | re.S,
                        ):
                            name = _identifier(match[1])
                            if name in Base.metadata.tables:
                                tables_seen.add(name)
                            create_columns[name] = re.findall(
                                r'^\s*"?(\w+)"?\s+(?!KEY\b)', match[2], re.M
                            )
                        elif re.match(
                            r"^(?:SET|SELECT\s+(?:pg_catalog\.)?setval|SELECT\s+pg_catalog.set_config|ALTER|CREATE|COMMENT|GRANT|REVOKE|DROP|BEGIN|COMMIT|END)\b",
                            sql,
                            re.I,
                        ):
                            setting = re.match(
                                r"SET standard_conforming_strings\s*=\s*(on|off)",
                                sql,
                                re.I,
                            )
                            if setting:
                                standard_strings = setting[1].lower() == "on"
                        else:
                            raise RestoreError(
                                "دستور SQL ناشناخته در فایل بک‌آپ وجود دارد."
                            )
                    if not quoted and statement and not statement.nonspace:
                        statement.clear()
                if (
                    copy_target
                    or quoted
                    or dollar
                    or block_comment
                    or statement.nonspace
                ):
                    raise RestoreError("بک‌آپ ناقص یا بریده شده است.")
                if postgres_dump and not dump_complete:
                    raise RestoreError(
                        "نشانهٔ پایان دامپ PostgreSQL وجود ندارد؛ فایل ناقص است."
                    )
        required = {"user", "file", "channel"}
        if not required <= tables_seen:
            raise RestoreError(
                "بک‌آپ کامل نیست؛ جدول‌های user، file و channel لازم هستند."
            )
        # Check owner references without holding the dataset in memory.
        missing = db.execute("""SELECT 1 FROM rows f WHERE table_name='file' AND NOT EXISTS
            (SELECT 1 FROM identities u WHERE u.table_name='user' AND u.name='userid'
             AND u.value=CAST(json_extract(f.payload,'$.owner_id') AS TEXT)) LIMIT 1""").fetchone()
        ambiguous = db.execute("""SELECT 1 FROM rows f JOIN owners a ON a.id=json_extract(f.payload,'$.owner_id')
            JOIN owners b ON b.userid=json_extract(f.payload,'$.owner_id')
            WHERE f.table_name='file' AND a.userid!=b.userid LIMIT 1""").fetchone()
        if ambiguous and owner_column is None:
            raise RestoreError("مالکیت فایل‌ها مبهم است؛ بک‌آپ دارای schema لازم است.")
        if owner_column == "id" or (missing and owner_column is None):
            pk_missing = db.execute("""SELECT 1 FROM rows f WHERE table_name='file' AND NOT EXISTS
                (SELECT 1 FROM owners u WHERE u.id=json_extract(f.payload,'$.owner_id')) LIMIT 1""").fetchone()
            if pk_missing:
                raise RestoreError(
                    "مالکیت فایل‌ها مبهم است؛ برای تبدیل owner_id بک‌آپ دارای schema لازم است."
                )
            db.execute("""UPDATE rows SET payload=json_set(payload,'$.owner_id',
                (SELECT userid FROM owners WHERE id=json_extract(rows.payload,'$.owner_id')))
                WHERE table_name='file'""")
        elif missing:
            raise RestoreError("مالک بعضی فایل‌ها در بک‌آپ کاربران وجود ندارد.")
        if (
            counts["bot_settings"] > 1
            or db.execute(
                "SELECT 1 FROM rows WHERE table_name='bot_settings' AND json_extract(payload,'$.id') != 1"
            ).fetchone()
        ):
            raise RestoreError("شناسهٔ تنظیمات ربات باید ۱ باشد.")
        db.commit()
        digest = _digest(spool)
        return PreparedRestore(
            spool,
            {name: counts[name] for name in Base.metadata.tables},
            version,
            source_format,
            digest,
        )
    except (
        UnicodeError,
        json.JSONDecodeError,
        EOFError,
        OSError,
        KeyError,
        TypeError,
    ) as error:
        raise RestoreError("فایل بک‌آپ خراب است یا قالب آن پشتیبانی نمی‌شود.") from error
    finally:
        db.close()


def _chain(first, iterator):
    yield first
    yield from iterator


async def prepare_restore(path: str | Path) -> PreparedRestore:
    path = Path(path)
    directory = backup_directory()
    handle, spool_path = tempfile.mkstemp(
        prefix="restore-", suffix=".sqlite3", dir=directory
    )
    import os

    os.close(handle)
    spool = Path(spool_path)
    normalized = None
    expanded = None
    stop = threading.Event()
    try:
        if path.stat().st_size > config(
            "RESTORE_MAX_BYTES", default=2 * 1024**3, cast=int
        ):
            raise RestoreError("فایل بک‌آپ بیش از حد بزرگ است.")
        with path.open("rb") as stream:
            signature = stream.read(512)
        if signature.startswith(b"\x1f\x8b"):
            with gzip.open(path, "rb") as stream:
                signature = stream.read(512)
            if signature.startswith(b"PGDMP") or signature[257:262] == b"ustar":
                expanded = spool.with_suffix(".archive")

                def expand():
                    total = 0
                    with gzip.open(path, "rb") as source, expanded.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            if stop.is_set():
                                raise RestoreError("بازیابی لغو شد.")
                            total += len(chunk)
                            if total > config(
                                "RESTORE_MAX_BYTES", default=2 * 1024**3, cast=int
                            ):
                                raise RestoreError(
                                    "حجم آرشیو بازشده بیش از حد مجاز است."
                                )
                            output.write(chunk)

                await run_blocking(expand, on_cancel=stop.set)
                path = expanded
        source_format = "sql"
        if signature.startswith(b"PGDMP") or signature[257:262] == b"ustar":
            source_format = "archive"
            normalized = spool.with_suffix(".sql")
            process = await asyncio.create_subprocess_exec(
                await find_pg_tool("pg_restore"),
                "--data-only",
                "--no-owner",
                "--no-acl",
                "--file=-",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            error_task = asyncio.create_task(process.stderr.read())

            async def extract():
                total = 0
                with normalized.open("wb") as output:
                    while chunk := await process.stdout.read(1024 * 1024):
                        total += len(chunk)
                        if total > config(
                            "RESTORE_MAX_BYTES", default=2 * 1024**3, cast=int
                        ):
                            raise RestoreError("حجم SQL آرشیو بیش از حد مجاز است.")
                        await run_blocking(output.write, chunk)
                await process.wait()
                return await error_task

            try:
                error = await asyncio.wait_for(
                    extract(), config("PG_TOOL_TIMEOUT", default=900, cast=int)
                )
            except BaseException:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                error_task.cancel()
                await asyncio.gather(error_task, return_exceptions=True)
                raise
            if process.returncode:
                LOGGER.warning(
                    "pg_restore extraction failed: %s",
                    error.decode(errors="replace")[:1000],
                )
                raise RestoreError(
                    "آرشیو قابل خواندن نیست؛ pg_restore هم‌نسخه یا جدیدتر از pg_dump را نصب کنید."
                )
            path = normalized
        return await run_blocking(_parse, path, spool, source_format, stop, on_cancel=stop.set)
    except BaseException:
        spool.unlink(missing_ok=True)
        raise
    finally:
        if normalized:
            normalized.unlink(missing_ok=True)
        if expanded:
            expanded.unlink(missing_ok=True)


async def apply_restore(
    prepared: PreparedRestore, *, on_restored=None, expected_generation=None
) -> RestoreResult:
    """Replace all application rows atomically, keeping current Alembic schema."""
    if await run_blocking(_digest, prepared.spool) != prepared.digest:
        raise RestoreError("فایل آمادهٔ بازیابی پس از پیش‌نمایش تغییر کرده است.")
    safety = (
        backup_directory()
        / f"before-restore-{datetime.now():%Y%m%d-%H%M%S}-{prepared.spool.stem}.jsonl.gz"
    )
    async with get_gate().restoration():
        if (
            expected_generation is not None
            and get_gate().generation != expected_generation
        ):
            raise RestoreError(
                "دیتابیس پس از پیش‌نمایش بازیابی دیگری داشته است؛ فایل را دوباره ارسال کنید."
            )
        get_cache().begin_restore()
        async with get_engine().connect() as connection:
            if connection.dialect.name == "postgresql":
                connection = await connection.execution_options(
                    isolation_level="REPEATABLE READ"
                )
            async with connection.begin():
                if connection.dialect.name == "postgresql":
                    tables = ",".join(
                        '"' + table.name + '"' for table in Base.metadata.sorted_tables
                    )
                    await connection.execute(
                        text(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE")
                    )
                else:
                    await connection.execute(text("BEGIN IMMEDIATE"))
                await export_data(connection, safety)
                for table in reversed(Base.metadata.sorted_tables):
                    await connection.execute(delete(table))
                db = sqlite3.connect(prepared.spool)
                try:
                    for table in Base.metadata.sorted_tables:
                        cursor = db.execute(
                            "SELECT payload FROM rows WHERE table_name=?", (table.name,)
                        )
                        while batch := cursor.fetchmany(2000):
                            rows = [
                                decode_row(table, json.loads(item[0])) for item in batch
                            ]
                            if (
                                connection.dialect.name == "postgresql"
                                and connection.dialect.driver == "asyncpg"
                            ):
                                raw = await connection.get_raw_connection()
                                columns = list(table.columns.keys())
                                await raw.driver_connection.copy_records_to_table(
                                    table.name,
                                    schema_name="public",
                                    columns=columns,
                                    records=[
                                        tuple(row[name] for name in columns)
                                        for row in rows
                                    ],
                                )
                            else:
                                await connection.execute(insert(table), rows)
                        if connection.dialect.name == "postgresql":
                            # setval is not transactional. Set only after all inserts are
                            # validated; rollback can only create harmless sequence gaps.
                            maximum = await connection.scalar(
                                select(table.c.id).order_by(table.c.id.desc()).limit(1)
                            )
                            await connection.execute(
                                text(
                                    "SELECT pg_catalog.setval(pg_get_serial_sequence(:table, 'id'), GREATEST(:value, nextval(pg_get_serial_sequence(:table, 'id'))), true)"
                                ),
                                {
                                    "table": '"' + table.name + '"',
                                    "value": max(maximum or 0, 1),
                                },
                            )
                finally:
                    db.close()
        cache = get_cache()
        cancellation = None
        try:
            await cache.reset_after_restore()
        except asyncio.CancelledError as error:
            # The SQL transaction is already committed. Never leave its old
            # Redis namespace enabled if the caller cancels during cleanup.
            cache.require_reset()
            cancellation = error
        except Exception:
            cache.enabled = False
            LOGGER.exception("Restore committed; Redis reset failed")
        if on_restored:
            try:
                await on_restored()
            except Exception:
                LOGGER.exception("Restore committed; runtime cleanup failed")
        if cancellation is not None:
            raise cancellation
    # Refresh planner statistics after bulk loading. Failure must not be reported
    # as a failed transaction after data has already committed.
    try:
        async with get_engine().begin() as connection:
            await connection.execute(text("ANALYZE"))
    except Exception:
        LOGGER.warning(
            "Restore committed; planner statistics refresh failed", exc_info=True
        )
    return RestoreResult(prepared.counts, str(safety))
