import asyncio
import gzip
import json
from pathlib import Path

import pytest
from sqlalchemy import event, select
from core.cache import get_cache
from core.database import get_engine, session_scope
from core.maintenance import get_gate
from core.models import File, User
from services.backup import create_data_backup
from services.restore import RestoreError, prepare_restore, apply_restore
from services.file import read_file_from_db, save_file_fields
from services.user import create_user_from_db, read_user_from_db


def sql_fixture():
    # Build COPY separators explicitly so escaped tabs/newlines in captions survive.
    return "\n".join(
        [
            "-- Dumped from database version 18.0",
            "SET transaction_timeout = 0;",
            'COPY public."user" (id, userid, phone_number, created_at, is_superuser, is_staff) FROM stdin;',
            "\t".join(
                ["10", "5000000001", r"\N", "2025-01-02 12:00:00+03:30", "t", "f"]
            ),
            r"\.",
            "COPY public.file (id, type, size, code, file_id, access_hash, file_reference, message_id, count, password, caption, created_at, owner_id) FROM stdin;",
            "\t".join(
                [
                    "9",
                    "photo",
                    "100",
                    "old_code",
                    "8000000000001",
                    "-6000000000001",
                    r"\\x00ff726566",
                    "55",
                    "2",
                    "secret",
                    r"متن\nخط دوم\tو تب\\مسیر",
                    "2025-01-02 12:00:00+03:30",
                    "5000000001",
                ]
            ),
            r"\.",
            "COPY public.channel (id, channel_id, channel_link, created_at, is_active) FROM stdin;",
            "\t".join(
                ["2", "-10055", "https://t.me/old", "2025-01-02 12:00:00+03:30", "t"]
            ),
            r"\.",
            "SELECT pg_catalog.setval('public.user_id_seq', 10, true);",
            "",
        ]
    )


@pytest.mark.parametrize("schema", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("version", ["12.22", "16.15", "18.0"])
async def test_full_and_data_only_copy_cross_version(
    schema, compressed, version, tmp_path, monkeypatch, make_file
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backup"))
    old = await make_file()
    content = sql_fixture().replace("18.0", version)
    if schema:
        content = (
            '-- schema\nCREATE TABLE public."user" (id integer, userid bigint);\n'
            + content
        )
    content = "\\restrict test_key\n" + content + "\\unrestrict test_key\n"
    path = tmp_path / "dump.sql"
    path.write_bytes(
        gzip.compress(content.encode()) if compressed else content.encode()
    )
    prepared = await prepare_restore(path)
    try:
        assert prepared.source_version == version and prepared.counts["file"] == 1
        result = await apply_restore(prepared)
        restored = await read_file_from_db("old_code")
        assert restored.file_reference == b"\0\xffref"
        assert (
            restored.file_id == 8000000000001 and restored.access_hash == -6000000000001
        )
        assert restored.caption == "متن\nخط دوم\tو تب\\مسیر"
        assert restored.password == "secret" and restored.count == 2
        assert restored.owner.userid == old.owner_id
        assert restored.created_at.utcoffset().total_seconds() == 0
        assert restored.album_order == 0 and restored.expires_at is None
        assert await read_file_from_db(old.code) is None
        safety = await prepare_restore(result.safety_backup)
        try:
            await apply_restore(safety)
            assert await read_file_from_db(old.code) is not None
        finally:
            safety.close()
    finally:
        prepared.close()


async def test_portable_roundtrip_all_tables_binary_and_unicode(
    tmp_path, monkeypatch, make_file
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    from services.settings import set_global_caption
    from services.analytics import create_broadcast_job, record_file_access

    file = await make_file(caption="'\"\\\nکپشن", password="secret", max_downloads=5)
    await set_global_caption("عمومی")
    await create_broadcast_job(
        admin_id=file.owner_id, delivery_type="copy", audience="all"
    )
    await record_file_access(42, file)
    path = await create_data_backup()
    prepared = await prepare_restore(path)
    try:
        assert (
            prepared.counts["bot_settings"]
            == prepared.counts["broadcast_job"]
            == prepared.counts["file_access_log"]
            == 1
        )
        file.caption = "changed"
        await save_file_fields(file, "caption")
        await apply_restore(prepared)
        restored = await read_file_from_db(file.code)
        assert (
            restored.caption == "'\"\\\nکپشن"
            and restored.file_reference == file.file_reference
        )
        assert restored.max_downloads == 5
    finally:
        prepared.close()


async def test_literal_inserts_and_escaped_bytea(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    path = tmp_path / "inserts.sql"
    path.write_text(
        """CREATE TABLE public."user" (\n id integer,\n userid bigint,\n created_at timestamp\n);
INSERT INTO public."user" VALUES (10, 5000000001, '2025-01-02 12:00:00+00');
INSERT INTO public.file (id,type,size,code,file_id,access_hash,file_reference,message_id,count,password,caption,created_at,owner_id) VALUES
(9,'photo',100,'code',8000000000001,-6000000000001,'\\x00ff',55,2,NULL,'a; ''quoted''\nمتن','2025-01-02 12:00:00+00',5000000001);
COPY public.channel (id,channel_id,channel_link,created_at,is_active) FROM stdin;
\\.
""",
        encoding="utf-8",
    )
    prepared = await prepare_restore(path)
    try:
        await apply_restore(prepared)
        file = await read_file_from_db("code")
        assert file.file_reference == b"\0\xff" and file.caption == "a; 'quoted'\r\nمتن"
    finally:
        prepared.close()


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("\\.\nCOPY public.channel", "\nCOPY public.channel"),
        lambda s: s.replace("5000000001\n\\.", "99999\n\\."),
        lambda s: s.replace("COPY public.channel", "COPY public.unknown"),
        lambda s: s + "\\! echo unsafe\n",
        lambda s: s.replace("is_active)", "unknown_column)"),
        lambda s: s.replace("\\x00ff726566", "\\xinvalid"),
        lambda s: s + "INSERT INTO public.file(id) VALUES (pg_sleep(1));\n",
    ],
)
async def test_invalid_uploads_never_change_existing_data(
    change, tmp_path, monkeypatch, make_file
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    file = await make_file()
    path = tmp_path / "bad.sql"
    path.write_text(change(sql_fixture()), encoding="utf-8")
    with pytest.raises(RestoreError):
        await prepare_restore(path)
    assert await read_file_from_db(file.code) is not None
    assert not list(tmp_path.glob("restore-*.sqlite3"))


async def test_failed_transaction_rolls_back_and_retains_safety_backup(
    tmp_path, monkeypatch, make_file
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    file = await make_file()
    path = tmp_path / "snapshot.sql"
    path.write_text(sql_fixture(), encoding="utf-8")
    prepared = await prepare_restore(path)

    def fail_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO file "):
            raise RuntimeError("injected write failure")

    event.listen(get_engine().sync_engine, "before_cursor_execute", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            await apply_restore(prepared)
    finally:
        event.remove(get_engine().sync_engine, "before_cursor_execute", fail_insert)
        prepared.close()
    assert await read_file_from_db(file.code) is not None
    assert await read_file_from_db("old_code") is None
    assert list(tmp_path.glob("before-restore-*.jsonl.gz"))


async def test_exclusive_restore_waits_for_operations():
    gate = get_gate()
    started, release = asyncio.Event(), asyncio.Event()

    async def operation():
        async with gate.operation():
            started.set()
            await release.wait()
            # Nested sessions remain possible while a writer is waiting.
            async with gate.operation():
                pass

    task = asyncio.create_task(operation())
    await started.wait()

    async def restore():
        async with gate.restoration():
            assert not gate.readers

    writer = asyncio.create_task(restore())
    await asyncio.sleep(0)
    assert not writer.done()
    release.set()
    await asyncio.gather(task, writer)
    assert gate.generation == 1


@pytest.mark.parametrize("with_schema", [False, True])
async def test_legacy_primary_key_ownership_maps_to_telegram_id(
    with_schema, tmp_path, monkeypatch
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    content = sql_fixture().replace("5000000001\n\\.", "10\n\\.")
    if with_schema:
        content += 'ALTER TABLE ONLY public.file ADD CONSTRAINT owner_fk FOREIGN KEY (owner_id) REFERENCES public."user"(id);\n'
    path = tmp_path / "owners.sql"
    path.write_text(content, encoding="utf-8")
    prepared = await prepare_restore(path)
    try:
        await apply_restore(prepared)
        assert (await read_file_from_db("old_code")).owner_id == 5000000001
    finally:
        prepared.close()


async def test_portable_truncated_payload_is_rejected(tmp_path, monkeypatch, make_file):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    await make_file()
    snapshot = Path(await create_data_backup())
    lines = gzip.decompress(snapshot.read_bytes()).splitlines(keepends=True)
    snapshot.write_bytes(gzip.compress(b"".join(lines[:-1])))
    with pytest.raises(RestoreError, match="ناقص"):
        await prepare_restore(snapshot)
