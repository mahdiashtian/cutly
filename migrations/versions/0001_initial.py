"""Initial schema.

Frozen history: a migration must not import application code, which keeps
changing after it. ``tests/test_migrations.py`` checks that the migrations build
exactly the schema the ORM models describe.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

MEDIA_TYPES = ("photo", "video", "animation", "audio", "voice", "sticker", "document")
MODES = ("copy", "forward")
AUDIENCES = ("all", "new", "active", "inactive", "channel")
STATUSES = ("scheduled", "queued", "running", "completed", "cancelled", "failed")

TZ = sa.DateTime(timezone=True)
BIG_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
# Tables updated in place all the time (download counter, activity time). Free
# space in each page lets PostgreSQL do HOT updates: the new row version stays
# on the same page and none of the table's indexes has to be rewritten.
UPDATE_HEAVY_TABLES = ("links", "users")
FILLFACTOR = 90


def _enum(values: tuple[str, ...], name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=16)


def _created_at() -> sa.Column:
    return sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("access_hash", sa.BigInteger()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_active_at", TZ),
        _created_at(),
    )
    op.create_index("ix_users_created_at", "users", ["created_at"])
    op.create_index("ix_users_admins", "users", ["id"],
                    postgresql_where=sa.text("is_admin"), sqlite_where=sa.text("is_admin = 1"))

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
        "bot_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("global_caption", sa.Text()),
        sa.Column("show_file_captions", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("mode", _enum(MODES, "broadcast_mode"), nullable=False),
        sa.Column("audience", _enum(AUDIENCES, "broadcast_audience"), nullable=False),
        sa.Column("channel_ref", sa.String(255)),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=False),
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

    if op.get_bind().dialect.name == "postgresql":
        for table in UPDATE_HEAVY_TABLES:
            op.execute(f"ALTER TABLE {table} SET (fillfactor = {FILLFACTOR})")


def downgrade() -> None:
    for table in ("broadcasts", "bot_settings", "mandatory_channels", "link_views", "link_media", "links", "users"):
        op.drop_table(table)
