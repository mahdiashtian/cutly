"""Run the same public-service contract against legacy or rewritten source."""

import asyncio
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

source = Path(sys.argv[1]).resolve()
database = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(source))
os.environ.update(
    API_ID="12345",
    API_HASH="0" * 32,
    BOT_TOKEN="test",
    REDIS_ENABLED="false",
    DB_URL="sqlite://" + database.as_posix(),
)

from core.database import init_db, close_db
from services import (
    change_admin_from_db,
    create_broadcast_job,
    create_channel_from_db,
    create_file_from_db,
    create_user_from_db,
    delete_channel_from_db,
    delete_file_from_db,
    finish_broadcast_job,
    get_dashboard_statistics,
    get_user_access_page,
    read_channels_from_db,
    read_files_from_db,
    read_users,
    record_file_access,
    set_global_caption,
    set_show_file_captions,
    userid_list,
)
from utils.helpers import send_file, build_file_caption


async def run():
    await init_db()
    owner = await create_user_from_db({"userid": 5_000_000_001, "phone_number": "123"})
    repeated = await create_user_from_db({"userid": owner.userid})
    await create_user_from_db({"userid": 42})
    await change_admin_from_db(42, is_staff=True)
    result = {
        "repeat_user": owner.id == repeated.id,
        "users": sorted(await userid_list()),
        "admins": [u.userid for u in await read_users(is_admin=True)],
    }
    await create_channel_from_db(
        {"channel_id": "test", "channel_link": "https://t.me/test"}
    )
    result["channels"] = [
        (c.channel_id, c.channel_link) for c in await read_channels_from_db()
    ]
    result["remove_channel"] = await delete_channel_from_db("https://t.me/test")
    settings = await set_global_caption("global")
    result["captions"] = [build_file_caption("local", settings)]
    settings = await set_show_file_captions(False)
    result["captions"].append(build_file_caption("local", settings))
    await set_show_file_captions(True)

    async def file(code, **values):
        return await create_file_from_db(
            dict(
                type="photo",
                size=2048,
                code=code,
                file_id=8_000_000_000_001,
                access_hash=-6_000_000_000_001,
                file_reference=b"\x00\xffref",
                message_id=55,
                owner_id=owner.userid,
                **values,
            )
        )

    first = await file("album", album_id="group", album_order=0, caption="local")
    await file("album_part1", album_id="group", album_order=1)
    calls = []

    async def deliver(chat_id, **kwargs):
        media = kwargs["file"]
        captions = kwargs["caption"]
        calls.append(
            {
                "ids": [f.id for f in media] if isinstance(media, list) else [media.id],
                "captions": captions,
            }
        )
        return [SimpleNamespace(id=1), SimpleNamespace(id=2)]

    client = SimpleNamespace(send_file=deliver)
    await send_file(
        client, 100, first, bot_username="bot", keyboard=[], storage_channel_id=-100
    )
    result["delivery"] = calls
    result["files"] = [
        (f.code, f.count, f.owner_id, f.file_reference.hex())
        for f in await read_files_from_db()
    ]
    result["wrong_owner_delete"] = await delete_file_from_db(42, "album")
    await record_file_access(42, first)
    await record_file_access(42, first)
    rows, total, user = await get_user_access_page(42, 0)
    result["access_log"] = {
        "total": total,
        "user": user.userid,
        "counts": [(r["file_code"], r["view_count"]) for r in rows],
    }
    job = await create_broadcast_job(admin_id=42, delivery_type="copy", audience="all")
    await finish_broadcast_job(job, total=2, success=1, failed=1)
    result["statistics"] = await get_dashboard_statistics()
    result["album_delete"] = await delete_file_from_db(owner.userid, "album")
    result["files_after_delete"] = len(await read_files_from_db())
    # Retain a protected binary row and bot settings for migration verification.
    await file("protected", password="secret", caption="کپشن", max_downloads=5, count=2)
    await close_db()
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    if len(sys.argv) > 3:
        with closing(sqlite3.connect(database)) as connection:
            Path(sys.argv[3]).write_text(
                "\n".join(connection.iterdump()), encoding="utf-8"
            )


asyncio.run(run())
