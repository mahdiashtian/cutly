from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon import events

from core.state import State
from services.backup import create_data_backup
from services import create_user_from_db, read_user_from_db


async def stopped(handler, event):
    try:
        await handler(event)
    except events.StopPropagation:
        pass


async def test_restore_upload_preview_confirm_and_reset(
    app, event_factory, telegram, make_file, tmp_path, monkeypatch
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    file = await make_file()
    snapshot = Path(await create_data_backup()).read_bytes()
    await create_user_from_db({"userid": 42})
    app.USER_LIST.extend([42, file.owner_id])
    app.CONVERSATION_OBJECT[42] = file
    await stopped(
        app.handle_restore_prompt, event_factory("♻️ بازیابی بک‌آپ", user_id=999)
    )
    assert app.CONVERSATION_STATE[999] == State.USER_RESTORE_UPLOAD

    async def download(message, file):
        Path(file).write_bytes(snapshot)
        return file

    telegram.download_media = AsyncMock(side_effect=download)
    upload = event_factory(user_id=999)
    upload.message.document = SimpleNamespace(size=len(snapshot))
    await stopped(app.handle_restore_upload, upload)
    assert app.CONVERSATION_STATE[999] == State.USER_RESTORE_CONFIRM
    assert await read_user_from_db(42) is not None  # Preview is read-only.
    assert not list(tmp_path.glob("upload-*.backup"))
    await stopped(
        app.handle_restore_confirm, event_factory("✅ تأیید بازیابی", user_id=999)
    )
    assert await read_user_from_db(42) is None
    assert not app.USER_LIST and not app.CONVERSATION_OBJECT
    assert app.CHANNEL_JOIN_LIST is None and not app.RESTORE_DRAFTS
    assert app.CONVERSATION_STATE[999] == State.USER_ADMIN_PANEL
    assert telegram.send_file.call_args.kwargs["caption"].startswith("✅")


async def test_back_cancels_restore_preview(
    app, event_factory, telegram, make_file, tmp_path, monkeypatch
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    await make_file()
    from services.restore import prepare_restore
    import time

    prepared = await prepare_restore(await create_data_backup())
    app.RESTORE_DRAFTS[999] = (prepared, time.monotonic())
    app.CONVERSATION_STATE[999] = State.USER_RESTORE_CONFIRM
    await stopped(app.handle_back, event_factory("🔙 بازگشت", user_id=999))
    assert not prepared.spool.exists() and not app.RESTORE_DRAFTS
    assert app.CONVERSATION_STATE[999] == State.USER_ADMIN_PANEL
