from __future__ import annotations

import gzip
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


def _rewrite(source: Path, target: Path, change) -> Path:
    """Copy a real backup, letting ``change`` edit its decoded lines."""
    with gzip.open(source, "rt", encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle]
    change(lines)
    with gzip.open(target, "wt", encoding="utf-8") as handle:
        handle.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
    return target


async def test_tampered_backup_is_rejected(tmp_path, container, empty_target):
    await _populate(container)
    backup = await container.backups.export_data()

    def tamper(lines):
        lines[1]["row"]["admin_id"] = 999  # a row changed after the checksum was taken

    with pytest.raises(RestoreError):
        empty_target.restores.stage(_rewrite(backup, tmp_path / "bad.jsonl.gz", tamper))
    assert not list((tmp_path / "backup").glob("staging-*"))  # nothing left behind


async def test_backup_from_an_unknown_schema_is_rejected(tmp_path, container, empty_target):
    backup = await container.backups.export_data()

    def unknown_revision(lines):
        lines[0]["revision"] = "9999_future"

    with pytest.raises(RestoreError):
        empty_target.restores.stage(_rewrite(backup, tmp_path / "future.jsonl.gz", unknown_revision))


async def test_non_backup_file_is_rejected(tmp_path, empty_target):
    path = tmp_path / "x.gz"
    with gzip.open(path, "wt") as output:
        output.write("hello\n")
    with pytest.raises(RestoreError):
        empty_target.restores.stage(path)
