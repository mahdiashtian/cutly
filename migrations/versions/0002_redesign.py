"""Redesigned schema: users keyed by Telegram id, links + link_media, durable broadcasts.

Old -> new:

* ``user``            -> ``users``  (Telegram id is the primary key; ``is_superuser``
  and ``is_staff`` merge into ``is_admin``; the never-written ``phone_number`` goes)
* ``file``            -> ``links`` (one per share link) + ``link_media`` (one per item).
  An album's settings and counter come from its first row, exactly as the old
  code read them; ``CODE_partN`` rows become positions of the same link.
* ``file_access_log`` -> ``link_views`` (by link id, not by code string)
* ``channel``         -> ``mandatory_channels`` (+ title, refreshed by the worker)
* ``broadcast_job``   -> ``broadcasts`` (history kept; in-memory jobs are gone)
* ``bot_settings``    unchanged
* link passwords are stored as scrypt hashes instead of plain text

Data moves with set-based ``INSERT … SELECT`` statements, so the database does
the work (no row-by-row Python), on PostgreSQL and SQLite alike.

This file is frozen history: it must not import application code, which will
keep changing after it.
"""
from __future__ import annotations

import base64
import hashlib
import secrets

import sqlalchemy as sa
from alembic import op

revision = "0002_redesign"
down_revision = "0001_sqlalchemy"
branch_labels = None
depends_on = None

MEDIA_TYPES = ("photo", "video", "animation", "audio", "voice", "sticker", "document")
MODES = ("copy", "forward")
AUDIENCES = ("all", "new", "active", "inactive", "channel")
STATUSES = ("scheduled", "queued", "running", "completed", "cancelled", "failed")
LEGACY_AUDIENCES = {
    "🆕 کاربران جدید": "new",
    "🟢 کاربران فعال": "active",
    "⚪ کاربران غیرفعال": "inactive",
    "📢 اعضای کانال": "channel",
}

TZ = sa.DateTime(timezone=True)
BIG_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _enum(values: tuple[str, ...], name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=16)


def _created_at() -> sa.Column:
    return sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    _create_tables()
    _copy_data()
    _hash_passwords()
    for table in ("file_access_log", "file", "broadcast_job", "channel", "user"):
        op.drop_table(table)


def downgrade() -> None:
    raise RuntimeError("Restore a backup taken before this migration to go back.")


def _create_tables() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("access_hash", sa.BigInteger()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_active_at", TZ),
        _created_at(),
    )
    op.create_index("ix_users_created_at", "users", ["created_at"])

    op.create_table(
        "links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("expires_at", TZ),
        sa.Column("max_downloads", sa.Integer()),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        _created_at(),
        sa.UniqueConstraint("code", name="uq_links_code"),
        sa.CheckConstraint("max_downloads IS NULL OR max_downloads > 0", name="ck_links_max_downloads"),
        sa.CheckConstraint("download_count >= 0", name="ck_links_download_count"),
    )
    op.create_index("ix_links_owner_id_created_at", "links", ["owner_id", "created_at"])
    op.create_index("ix_links_created_at", "links", ["created_at"])

    op.create_table(
        "link_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("media_type", _enum(MEDIA_TYPES, "media_type"), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("tg_file_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_access_hash", sa.BigInteger(), nullable=False),
        sa.Column("tg_file_reference", sa.LargeBinary(), nullable=False),
        sa.Column("storage_message_id", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("link_id", "position", name="uq_link_media_link_id_position"),
    )

    op.create_table(
        "link_views",
        sa.Column("id", BIG_PK, primary_key=True),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("viewer_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("viewed_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_link_views_viewer_id_link_id_viewed_at", "link_views", ["viewer_id", "link_id", "viewed_at"])
    op.create_index("ix_link_views_link_id", "link_views", ["link_id"])
    op.create_index("ix_link_views_viewed_at", "link_views", ["viewed_at"])

    op.create_table(
        "mandatory_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_ref", sa.String(255), nullable=False),
        sa.Column("invite_link", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("chat_ref", name="uq_mandatory_channels_chat_ref"),
    )

    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("mode", _enum(MODES, "broadcast_mode"), nullable=False),
        sa.Column("audience", _enum(AUDIENCES, "broadcast_audience"), nullable=False),
        sa.Column("channel_ref", sa.String(255)),
        sa.Column("source_chat_id", sa.BigInteger()),
        sa.Column("source_message_id", sa.Integer()),
        sa.Column("status", _enum(STATUSES, "broadcast_status"), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scheduled_at", TZ),
        sa.Column("cursor", sa.BigInteger()),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_message_id", sa.Integer()),
        sa.Column("started_at", TZ),
        sa.Column("heartbeat_at", TZ),
        sa.Column("finished_at", TZ),
        _created_at(),
    )
    op.create_index("ix_broadcasts_status_scheduled_at", "broadcasts", ["status", "scheduled_at"])
    op.create_index(
        "uq_broadcasts_single_running", "broadcasts", ["status"], unique=True,
        sqlite_where=sa.text("status = 'running'"), postgresql_where=sa.text("status = 'running'"),
    )


def _copy_data() -> None:
    old_user = sa.table(
        "user", sa.column("userid", sa.BigInteger), sa.column("created_at", TZ),
        sa.column("last_activity_at", TZ), sa.column("is_superuser", sa.Boolean), sa.column("is_staff", sa.Boolean),
    )
    old_file = sa.table(
        "file", *(sa.column(name) for name in (
            "id", "type", "size", "code", "file_id", "access_hash", "file_reference", "message_id", "count",
            "password", "caption", "album_id", "album_order", "created_at", "expires_at", "max_downloads", "owner_id",
        )),
    )
    old_log = sa.table("file_access_log", sa.column("viewer_id"), sa.column("file_code"), sa.column("accessed_at"))
    old_channel = sa.table("channel", sa.column("channel_id"), sa.column("channel_link"), sa.column("created_at"))
    old_job = sa.table("broadcast_job", *(sa.column(name) for name in (
        "admin_id", "delivery_type", "audience", "status", "total_count", "success_count", "failed_count",
        "scheduled_at", "started_at", "completed_at",
    )))
    users = sa.table("users", *(sa.column(n) for n in ("id", "is_admin", "created_at", "last_active_at")))
    links = sa.table("links", *(sa.column(n) for n in (
        "id", "code", "owner_id", "caption", "password_hash", "expires_at", "max_downloads", "download_count",
        "created_at",
    )))
    link_media = sa.table("link_media", *(sa.column(n) for n in (
        "link_id", "position", "media_type", "size", "tg_file_id", "tg_access_hash", "tg_file_reference",
        "storage_message_id",
    )))
    link_views = sa.table("link_views", sa.column("link_id"), sa.column("viewer_id"), sa.column("viewed_at"))
    channels = sa.table("mandatory_channels", *(sa.column(n) for n in ("chat_ref", "invite_link", "title", "created_at")))
    broadcasts = sa.table("broadcasts", *(sa.column(n) for n in (
        "admin_id", "mode", "audience", "status", "cancel_requested", "total", "succeeded", "failed",
        "scheduled_at", "started_at", "finished_at", "created_at",
    )))

    op.execute(sa.insert(users).from_select(
        ["id", "is_admin", "created_at", "last_active_at"],
        sa.select(old_user.c.userid, sa.or_(old_user.c.is_superuser, old_user.c.is_staff),
                  old_user.c.created_at, old_user.c.last_activity_at),
    ))

    # Rank each file inside its album (a standalone file is its own group).
    group = sa.func.coalesce(old_file.c.album_id, sa.literal("#") + sa.cast(old_file.c.id, sa.String))
    order = (old_file.c.album_order, old_file.c.id)
    ranked = sa.select(
        old_file,
        (sa.func.row_number().over(partition_by=group, order_by=order) - 1).label("position"),
        sa.func.first_value(old_file.c.code).over(partition_by=group, order_by=order).label("link_code"),
    ).subquery("ranked")

    op.execute(sa.insert(links).from_select(
        ["code", "owner_id", "caption", "password_hash", "expires_at", "max_downloads", "download_count",
         "created_at"],
        sa.select(ranked.c.code, ranked.c.owner_id, ranked.c.caption, ranked.c.password, ranked.c.expires_at,
                  ranked.c.max_downloads, ranked.c.count, ranked.c.created_at).where(ranked.c.position == 0),
    ))
    media_type = sa.case((ranked.c.type.in_(MEDIA_TYPES), ranked.c.type), else_=sa.literal("document"))
    op.execute(sa.insert(link_media).from_select(
        ["link_id", "position", "media_type", "size", "tg_file_id", "tg_access_hash", "tg_file_reference",
         "storage_message_id"],
        sa.select(links.c.id, ranked.c.position, media_type, ranked.c.size, ranked.c.file_id,
                  ranked.c.access_hash, ranked.c.file_reference, ranked.c.message_id)
        .select_from(ranked.join(links, links.c.code == ranked.c.link_code)),
    ))

    op.execute(sa.insert(link_views).from_select(
        ["link_id", "viewer_id", "viewed_at"],
        sa.select(links.c.id, old_log.c.viewer_id, old_log.c.accessed_at)
        .select_from(old_log.join(links, links.c.code == old_log.c.file_code))
        .where(old_log.c.viewer_id.in_(sa.select(users.c.id))),
    ))

    op.execute(sa.insert(channels).from_select(
        ["chat_ref", "invite_link", "title", "created_at"],
        sa.select(old_channel.c.channel_id, old_channel.c.channel_link, old_channel.c.channel_id,
                  old_channel.c.created_at),
    ))

    audience = sa.case(*((old_job.c.audience == label, code) for label, code in LEGACY_AUDIENCES.items()),
                       else_=sa.literal("all"))
    mode = sa.case((old_job.c.delivery_type == "forward", "forward"), else_=sa.literal("copy"))
    # Old scheduled/running jobs lived in process memory and are gone.
    status = sa.case((old_job.c.status.in_(("completed", "cancelled")), old_job.c.status),
                     else_=sa.literal("failed"))
    op.execute(sa.insert(broadcasts).from_select(
        ["admin_id", "mode", "audience", "status", "cancel_requested", "total", "succeeded", "failed",
         "scheduled_at", "started_at", "finished_at", "created_at"],
        sa.select(old_job.c.admin_id, mode, audience, status, sa.false(), old_job.c.total_count,
                  old_job.c.success_count, old_job.c.failed_count, old_job.c.scheduled_at, old_job.c.started_at,
                  old_job.c.completed_at,
                  sa.func.coalesce(old_job.c.started_at, old_job.c.scheduled_at, old_job.c.completed_at,
                                   sa.func.now())),
    ))


def _hash_passwords() -> None:
    """Plain-text passwords were copied above; replace each with its hash."""
    bind = op.get_bind()
    links = sa.table("links", sa.column("id"), sa.column("password_hash"))
    rows = bind.execute(sa.select(links.c.id, links.c.password_hash).where(links.c.password_hash.is_not(None)))
    for link_id, password in rows.all():
        bind.execute(sa.update(links).where(links.c.id == link_id).values(password_hash=_scrypt_hash(password)))


def _scrypt_hash(password: str) -> str:
    # Same format as core.security.hash_password (copied: migrations are frozen).
    n, r, p, salt = 2**14, 8, 1, secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(digest)}"


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")
