from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from container import Container
from core.enums import BroadcastAudience, BroadcastMode, MediaType
from core.security import verify_password
from services.restore import RestoreError
from tests.conftest import make_settings, media


@pytest.fixture
async def empty_target(tmp_path):
    container = Container(make_settings(tmp_path))
    await container.startup()
    await container.database.create_all()
    yield container
    await container.shutdown()


async def _populate(container: Container):
    await container.users.ensure(10, access_hash=99)
    await container.users.ensure(20)
    link = await container.links.create(10, [media(), media(MediaType.VIDEO)], expires_at=None, max_downloads=9)
    await container.links.set_password(link, "pw")
    await container.links.reserve_download(link)
    await container.links.record_view(link, 20)
    await container.channels.add(chat_ref="news", invite_link="https://t.me/news", title="News")
    await container.settings_service.set_global_caption("hello")
    await container.broadcasts.create(admin_id=10, mode=BroadcastMode.COPY, audience=BroadcastAudience.ALL,
                                      channel_ref=None, source_chat_id=10, source_message_id=5)
    return link


async def test_round_trip_into_an_empty_database(container, empty_target):
    link = await _populate(container)
    backup = await container.backups.export_data()

    staged = empty_target.restores.stage(backup)
    assert staged.counts == {"broadcasts": 1, "mandatory_channels": 1, "bot_settings": 1, "users": 2,
                             "links": 1, "link_media": 2, "link_views": 1}
    await empty_target.restores.apply(staged)

    restored = await empty_target.links.get(link.code)
    assert restored.media == link.media and verify_password("pw", restored.password_hash)
    items, _, _ = await empty_target.links.owned_page(10, 0, 5)
    assert items[0].download_count == 1
    assert (await empty_target.users.get(10)).access_hash == 99
    assert (await empty_target.settings_service.get()).global_caption == "hello"
    # New rows still get fresh ids after explicit ids were inserted.
    second = await empty_target.links.create(10, [media()], expires_at=None, max_downloads=None)
    assert second.id > restored.id


async def test_restore_replaces_existing_data(container, empty_target):
    await _populate(container)
    backup = await container.backups.export_data()
    await empty_target.users.ensure(777)
    await empty_target.restores.apply(empty_target.restores.stage(backup))
    assert await empty_target.users.profile(777) is None


def _legacy_backup(path: Path, *, tamper: bool = False) -> Path:
    """A version-2 snapshot exactly as the previous release wrote it."""
    rows = [
        ("bot_settings", {"id": 1, "global_caption": "g", "show_file_captions": True}),
        ("channel", {"id": 1, "channel_id": "news", "channel_link": "https://t.me/news",
                     "created_at": "2026-10-01T10:00:00+00:00", "is_active": True}),
        ("user", {"id": 1, "userid": 500, "phone_number": None, "created_at": "2026-10-01T10:00:00+00:00",
                  "last_activity_at": None, "is_superuser": False, "is_staff": True}),
        *(("file", {"id": index, "type": kind, "size": 10, "code": code, "file_id": index, "access_hash": index,
                    "file_reference": {"$bytes": base64.b64encode(b"r").decode()}, "message_id": index,
                    "count": 3, "password": "old", "caption": None, "album_id": "A", "album_order": index - 1,
                    "created_at": "2026-10-01T10:00:00+00:00", "expires_at": None, "max_downloads": None,
                    "owner_id": 500})
          for index, kind, code in ((1, "photo", "abc"), (2, "video", "abc_part1"))),
        ("file_access_log", {"id": 1, "viewer_id": 500, "file_code": "abc", "owner_id": 500,
                             "accessed_at": "2026-10-02T10:00:00+00:00"}),
    ]
    lines = [json.dumps({"table": table, "row": row}, ensure_ascii=False) + "\n" for table, row in rows]
    digest = hashlib.sha256("".join(lines).encode()).hexdigest()
    counts = {"bot_settings": 1, "broadcast_job": 0, "channel": 1, "file_access_log": 1, "user": 1, "file": 2}
    with gzip.open(path, "wt", encoding="utf-8") as output:
        output.write(json.dumps({"format": "cutly-data", "version": 2, "tables": list(counts)}) + "\n")
        output.writelines(lines)
        output.write(json.dumps({"end": True, "counts": counts, "sha256": "0" * 64 if tamper else digest}) + "\n")
    return path


async def test_legacy_backup_is_upgraded_by_the_migrations(tmp_path, empty_target):
    staged = empty_target.restores.stage(_legacy_backup(tmp_path / "old.jsonl.gz"))
    assert staged.source_version == 2
    assert staged.counts["links"] == 1 and staged.counts["link_media"] == 2 and staged.counts["link_views"] == 1
    await empty_target.restores.apply(staged)
    link = await empty_target.links.get("abc")
    assert [item.media_type for item in link.media] == [MediaType.PHOTO, MediaType.VIDEO]
    assert verify_password("old", link.password_hash)
    assert await empty_target.users.is_admin(500)


async def test_tampered_backup_is_rejected(tmp_path, empty_target):
    with pytest.raises(RestoreError):
        empty_target.restores.stage(_legacy_backup(tmp_path / "bad.jsonl.gz", tamper=True))
    assert not list((tmp_path / "backup").glob("staging-*"))  # nothing left behind


async def test_non_backup_file_is_rejected(tmp_path, empty_target):
    path = tmp_path / "x.gz"
    with gzip.open(path, "wt") as output:
        output.write("hello\n")
    with pytest.raises(RestoreError):
        empty_target.restores.stage(path)
