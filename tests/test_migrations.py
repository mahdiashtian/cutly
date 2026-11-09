"""The migration chain must (1) produce exactly the ORM schema and (2) convert
a database written by the previous release without losing anything."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, select, text

from core.security import verify_password
from db.base import Base
from db.migrations import upgrade
from db.models import Broadcast, Link, LinkMedia, LinkView, MandatoryChannel, User

LEGACY_SQL = Path(__file__).with_name("legacy.sql")


def _engine(path: Path):
    return create_engine(f"sqlite:///{path}")


def test_migrations_match_models(tmp_path):
    engine = _engine(tmp_path / "fresh.sqlite3")
    with engine.begin() as connection:
        upgrade(connection)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []


def test_legacy_database_is_converted(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as legacy:
        legacy.executescript(LEGACY_SQL.read_text(encoding="utf-8"))
        # An album of three items (the fixture only has a single file), plus a
        # view of it, as the previous release stored them.
        legacy.executescript("""
            INSERT INTO file VALUES(4,'photo',10,'album',1,11,X'01',101,7,NULL,'cap','A1',0,'2026-10-05 10:00:00+00:00',NULL,NULL,5000000001);
            INSERT INTO file VALUES(5,'video',20,'album_part1',2,12,X'02',102,7,NULL,'cap','A1',1,'2026-10-05 10:00:00+00:00',NULL,NULL,5000000001);
            INSERT INTO file VALUES(6,'weird',30,'album_part2',3,13,X'03',103,7,NULL,'cap','A1',2,'2026-10-05 10:00:00+00:00',NULL,NULL,5000000001);
            INSERT INTO channel VALUES(1,'-1001234','https://t.me/+abc','2026-10-04 22:00:00+00:00',1);
        """)
    engine = _engine(path)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        upgrade(connection)

    with engine.connect() as connection:
        users = {row.id: row for row in connection.execute(select(User.__table__))}
        assert set(users) == {5000000001, 42}
        assert users[42].is_admin and not users[5000000001].is_admin

        links = {row.code: row for row in connection.execute(select(Link.__table__))}
        assert set(links) == {"protected", "album"}  # the _part rows are not links any more
        assert verify_password("secret", links["protected"].password_hash)
        assert links["protected"].max_downloads == 5 and links["protected"].download_count == 2
        assert links["album"].caption == "cap" and links["album"].download_count == 7

        album = connection.execute(
            select(LinkMedia.position, LinkMedia.media_type, LinkMedia.tg_file_id, LinkMedia.storage_message_id)
            .where(LinkMedia.link_id == links["album"].id).order_by(LinkMedia.position)
        ).all()
        assert album == [(0, "photo", 1, 101), (1, "video", 2, 102), (2, "document", 3, 103)]
        single = connection.execute(select(LinkMedia.tg_file_reference)
                                    .where(LinkMedia.link_id == links["protected"].id)).scalar_one()
        assert single == b"\x00\xffref"

        views = connection.execute(select(LinkView.link_id, LinkView.viewer_id)).all()
        assert views == [(links["album"].id, 42)] * 2

        channel = connection.execute(select(MandatoryChannel.__table__)).one()
        assert (channel.chat_ref, channel.invite_link) == ("-1001234", "https://t.me/+abc")

        broadcast = connection.execute(select(Broadcast.__table__)).one()
        assert (broadcast.status, broadcast.audience, broadcast.succeeded) == ("completed", "all", 1)

        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert not tables & {"user", "file", "channel", "file_access_log", "broadcast_job"}
    engine.dispose()
