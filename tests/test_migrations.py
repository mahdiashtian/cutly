import ast
import json
import os
import re
from pathlib import Path
import sqlite3
from contextlib import closing
import subprocess
import sys
from alembic import command
import pytest
from sqlalchemy import text
from core.database import alembic_config, close_db, get_engine, init_db
from services import (
    create_user_from_db,
    get_bot_settings,
    get_dashboard_statistics,
    read_file_from_db,
)
from services.file_repository import FileRepository

FIXTURES = Path(__file__).parent / "fixtures"


async def seed_legacy(tmp_path, monkeypatch):
    await close_db()
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript((FIXTURES / "legacy.sql").read_text(encoding="utf-8"))
    monkeypatch.setenv("DB_URL", "sqlite://" + path.as_posix())
    return path


async def test_adopt_real_tortoise_schema_preserves_every_row(tmp_path, monkeypatch):
    path = await seed_legacy(tmp_path, monkeypatch)

    def rows():
        with closing(sqlite3.connect(path)) as connection:
            return {
                table: connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY id'
                ).fetchall()
                for table in (
                    "user",
                    "file",
                    "bot_settings",
                    "broadcast_job",
                    "file_access_log",
                )
            }

    before = rows()
    await init_db()
    await init_db()
    assert rows() == before
    file = await read_file_from_db("protected")
    assert file.password == "secret" and file.caption == "کپشن"
    assert (
        file.count == 2
        and file.max_downloads == 5
        and file.file_reference == b"\x00\xffref"
    )
    assert file.owner_id == 5_000_000_001 and file.owner.userid == file.owner_id
    assert (await get_bot_settings()).global_caption == "global"
    # Legacy AUTOINCREMENT sequences must continue after existing PKs.
    await create_user_from_db({"userid": 99})
    created = await FileRepository().create(
        dict(
            type=file.type,
            code="new",
            size=file.size,
            owner_id=file.owner_id,
            file_id=file.file_id,
            access_hash=file.access_hash,
            file_reference=file.file_reference,
            message_id=56,
        )
    )
    assert created.id > file.id
    async with get_engine().connect() as connection:
        assert (
            await connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0001_sqlalchemy"
        )


async def test_early_legacy_schema_gets_additions_and_missing_tables(
    tmp_path, monkeypatch
):
    path = await seed_legacy(tmp_path, monkeypatch)
    with closing(sqlite3.connect(path)) as connection:
        for table in ("bot_settings", "broadcast_job", "file_access_log"):
            connection.execute(f'DROP TABLE "{table}"')
        connection.execute('ALTER TABLE "user" DROP COLUMN last_activity_at')
        connection.execute('ALTER TABLE "file" DROP COLUMN expires_at')
        connection.execute('ALTER TABLE "file" DROP COLUMN max_downloads')
    await init_db()
    assert (await read_file_from_db("protected")).expires_at is None
    assert (await get_bot_settings()).show_file_captions
    assert (await get_dashboard_statistics())["total_users"] == 2


async def test_unknown_schema_rejected_without_dropping_data(tmp_path, monkeypatch):
    path = await seed_legacy(tmp_path, monkeypatch)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            'ALTER TABLE "file" RENAME COLUMN file_reference TO old_reference'
        )
    with pytest.raises(RuntimeError, match="Unsupported legacy table file"):
        await init_db()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('SELECT count(*) FROM "file"').fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM alembic_version").fetchone()[0]
            == 0
        )


async def test_incompatible_legacy_ownership_is_rejected(tmp_path, monkeypatch):
    await close_db()
    path = tmp_path / "wrong-owner.sqlite3"
    schema = (FIXTURES / "legacy.sql").read_text(encoding="utf-8")
    schema = schema.replace('REFERENCES "user" ("userid")', 'REFERENCES "user" ("id")')
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(schema)
    monkeypatch.setenv("DB_URL", "sqlite+aiosqlite:///" + path.as_posix())
    with pytest.raises(RuntimeError, match="Unsupported legacy file ownership"):
        await init_db()


async def test_fresh_schema_has_no_autogenerate_drift():
    async with get_engine().begin() as connection:

        def check(sync):
            cfg = alembic_config()
            cfg.attributes["connection"] = sync
            command.check(cfg)

        await connection.run_sync(check)


async def test_adopted_legacy_schema_has_no_autogenerate_drift(tmp_path, monkeypatch):
    await seed_legacy(tmp_path, monkeypatch)
    await init_db()
    async with get_engine().begin() as connection:

        def check(sync):
            cfg = alembic_config()
            cfg.attributes["connection"] = sync
            command.check(cfg)

        await connection.run_sync(check)


async def test_autogeneration_still_detects_a_new_index():
    from alembic.util.exc import AutogenerateDiffsDetected
    from sqlalchemy import Index
    from core.models import User

    index = Index("ix_user_activity_test", User.last_activity_at)
    try:
        async with get_engine().begin() as connection:

            def check(sync):
                cfg = alembic_config()
                cfg.attributes["connection"] = sync
                command.check(cfg)

            with pytest.raises(
                AutogenerateDiffsDetected, match="ix_user_activity_test"
            ):
                await connection.run_sync(check)
    finally:
        User.__table__.indexes.discard(index)


async def test_alembic_cli_upgrade_requires_no_telegram_credentials(tmp_path):
    path = tmp_path / "cli.sqlite3"
    env = os.environ.copy()
    for key in ("API_ID", "API_HASH", "BOT_TOKEN"):
        env.pop(key, None)
    env["DB_URL"] = "sqlite+aiosqlite:///" + path.as_posix()
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0001_sqlalchemy"
        )


async def test_rewritten_contract_matches_legacy_snapshot(tmp_path):
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent / "contract_scenario.py"),
            str(root),
            str(tmp_path / "contract.sqlite3"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(
        (FIXTURES / "contract.json").read_text(encoding="utf-8")
    )


def test_all_legacy_event_registrations_preserved():
    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    routes = {
        node.name: [ast.dump(decorator) for decorator in node.decorator_list]
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.decorator_list
    }
    expected = json.loads((FIXTURES / "routes.json").read_text(encoding="utf-8"))

    # Python versions differ in whether ast.dump displays empty list fields.
    def portable(values):
        return {
            name: [re.sub(r", \w+=\[\]", "", value) for value in definitions]
            for name, definitions in values.items()
        }

    # New requested backup/restore routes supplement the original business routes.
    assert portable({name: routes[name] for name in expected}) == portable(expected)
