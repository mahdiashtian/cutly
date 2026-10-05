"""Real cross-major dump tests; all databases are created and dropped by the test."""

import asyncio
import gzip
import os
import re
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import make_url

from core.database import close_db, init_db
from core.cache import get_cache
from services.backup import create_backup, create_data_backup
from services.restore import prepare_restore, apply_restore
from services import create_user_from_db, create_file_from_db, read_file_from_db


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "kind",
    [
        "full",
        "data",
        "inserts",
        "column-inserts",
        "custom",
        "custom-data",
        "tar",
        "gzip",
        "custom-gzip",
        "tar-gzip",
        "portable",
    ],
)
async def test_real_dump_cross_major_restore(reverse, kind, tmp_path, monkeypatch):
    dsns = [
        os.environ.get("CUTLY_TEST_POSTGRES_URL"),
        os.environ.get("CUTLY_TEST_POSTGRES_SECOND_URL"),
    ]
    if not all(dsns):
        pytest.skip(
            "Set two disposable PostgreSQL admin DSNs for cross-major restore tests"
        )
    if reverse:
        dsns.reverse()
    urls, admins, names = [], [], []
    actual_launch = asyncio.create_subprocess_exec
    runtime = os.environ.get("CUTLY_PG_TEST_WSL_RUNTIME")
    versions = ["18", "16"] if reverse else ["16", "18"]
    if runtime:
        roots = {"16": runtime, "18": os.environ["CUTLY_PG_TEST_WSL_SECOND_RUNTIME"]}

        async def launch(executable, *args, **kwargs):
            if executable.startswith("test_pg_"):
                _, _, name, version = executable.split("_")
                root = roots[version]
                translated = []
                for arg in args:
                    if re.match(r"^[A-Za-z]:[\\/]", str(arg)):
                        path = Path(arg).as_posix()
                        arg = "/mnt/" + path[0].lower() + path[2:]
                    translated.append(str(arg))
                return await actual_launch(
                    "wsl",
                    "-d",
                    "Ubuntu-24.04",
                    "--",
                    "env",
                    f"LD_LIBRARY_PATH={root}/usr/lib/x86_64-linux-gnu:{runtime}/usr/lib/x86_64-linux-gnu",
                    f"{root}/usr/lib/postgresql/{version}/bin/pg_{name}",
                    *translated,
                    **kwargs,
                )
            return await actual_launch(executable, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        monkeypatch.setenv("PG_DUMP_PATH", f"test_pg_dump_{versions[0]}")
        # Always read archives with the newest client, including 18 -> 16.
        monkeypatch.setenv("PG_RESTORE_PATH", "test_pg_restore_18")
    else:
        monkeypatch.setenv(
            "PG_DUMP_PATH", os.environ[f"CUTLY_TEST_PG_DUMP_{versions[0]}"]
        )
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    try:
        for dsn in dsns:
            url = make_url(dsn)
            admin = await asyncpg.connect(
                url.set(drivername="postgresql").render_as_string(hide_password=False)
            )
            name = "cutly_restore_" + uuid.uuid4().hex
            await admin.execute(f'CREATE DATABASE "{name}"')
            admins.append(admin)
            names.append(name)
            urls.append(url.set(database=name, drivername="postgresql+asyncpg"))
        await close_db()
        monkeypatch.setenv("DB_URL", urls[0].render_as_string(hide_password=False))
        await init_db()
        user = await create_user_from_db({"userid": 5000000001, "is_superuser": True})
        file = await create_file_from_db(
            dict(
                code="old",
                owner_id=user.userid,
                type="photo",
                size=1024,
                file_id=8000000000001,
                access_hash=-6000000000001,
                file_reference=b"\x00\xffref",
                message_id=55,
                password="secret",
                caption="a; 'quote'\nمتن",
                max_downloads=5,
            )
        )
        if kind == "portable":
            path = Path(await create_data_backup())
        elif kind in {"full", "gzip"}:
            path = Path(await create_backup())
            if kind == "gzip":
                target = tmp_path / "compressed.sql.gz"
                target.write_bytes(gzip.compress(path.read_bytes()))
                path = target
        else:
            path = tmp_path / "snapshot.dump"
            url = urls[0]
            options = {
                "data": ["--data-only"],
                "inserts": ["--data-only", "--inserts"],
                "column-inserts": ["--data-only", "--column-inserts"],
                "custom": ["-Fc"],
                "custom-data": ["-Fc", "--data-only"],
                "tar": ["-Ft"],
                "custom-gzip": ["-Fc"],
                "tar-gzip": ["-Ft"],
            }[kind]
            executable = os.environ["PG_DUMP_PATH"]
            process = await asyncio.create_subprocess_exec(
                executable,
                "-U",
                url.username,
                "-h",
                url.host,
                "-p",
                str(url.port),
                *options,
                "-f",
                str(path),
                url.database,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, error = await process.communicate()
            assert process.returncode == 0, error.decode(errors="replace")
            if kind.endswith("-gzip"):
                compressed = tmp_path / "archive.gz"
                compressed.write_bytes(gzip.compress(path.read_bytes()))
                path = compressed
        prepared = await prepare_restore(path)
        try:
            await close_db()
            await get_cache().clear_all()
            monkeypatch.setenv("DB_URL", urls[1].render_as_string(hide_password=False))
            await init_db()
            await create_user_from_db({"userid": 42})
            await apply_restore(prepared)
            restored = await read_file_from_db("old")
            assert restored.file_reference == file.file_reference
            assert (
                restored.caption == file.caption
                and restored.password == "secret"
                and restored.max_downloads == 5
            )
            assert restored.owner.userid == user.userid
            added = await create_user_from_db({"userid": 43})
            assert added.id > user.id
        finally:
            prepared.close()
    finally:
        await close_db()
        for admin, name in zip(admins, names):
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
            await admin.close()
