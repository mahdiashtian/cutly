"""Baseline: create new schemas or adopt legacy Tortoise tables without data loss."""

from alembic import op
import sqlalchemy as sa

revision = "0001_sqlalchemy"
down_revision = None
branch_labels = None
depends_on = None

TABLES = {
    "bot_settings": [
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("global_caption", sa.Text(), nullable=True, primary_key=False),
        sa.Column(
            "show_file_captions",
            sa.Boolean(),
            nullable=False,
            primary_key=False,
            server_default=sa.true(),
        ),
    ],
    "broadcast_job": [
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column("delivery_type", sa.String(16), nullable=False, primary_key=False),
        sa.Column("audience", sa.String(128), nullable=False, primary_key=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            primary_key=False,
            server_default="scheduled",
        ),
        sa.Column(
            "total_count",
            sa.Integer(),
            nullable=False,
            primary_key=False,
            server_default="0",
        ),
        sa.Column(
            "success_count",
            sa.Integer(),
            nullable=False,
            primary_key=False,
            server_default="0",
        ),
        sa.Column(
            "failed_count",
            sa.Integer(),
            nullable=False,
            primary_key=False,
            server_default="0",
        ),
        sa.Column(
            "scheduled_at", sa.DateTime(timezone=True), nullable=True, primary_key=False
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=True, primary_key=False
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True, primary_key=False
        ),
    ],
    "channel": [
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("channel_id", sa.String(255), nullable=False, primary_key=False),
        sa.Column("channel_link", sa.String(255), nullable=False, primary_key=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            primary_key=False,
            server_default=sa.true(),
        ),
    ],
    "file_access_log": [
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("viewer_id", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column("file_code", sa.String(32), nullable=False, primary_key=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column(
            "accessed_at", sa.DateTime(timezone=True), nullable=False, primary_key=False
        ),
    ],
    "user": [
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("userid", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column("phone_number", sa.String(32), nullable=True, primary_key=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
            primary_key=False,
        ),
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            nullable=False,
            primary_key=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_staff",
            sa.Boolean(),
            nullable=False,
            primary_key=False,
            server_default=sa.false(),
        ),
    ],
    "file": [
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("type", sa.String(64), nullable=False, primary_key=False),
        sa.Column("size", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column("code", sa.String(32), nullable=False, primary_key=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column("access_hash", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column(
            "file_reference", sa.LargeBinary(), nullable=False, primary_key=False
        ),
        sa.Column("message_id", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column(
            "count", sa.Integer(), nullable=False, primary_key=False, server_default="0"
        ),
        sa.Column("password", sa.String(255), nullable=True, primary_key=False),
        sa.Column("caption", sa.Text(), nullable=True, primary_key=False),
        sa.Column("album_id", sa.String(64), nullable=True, primary_key=False),
        sa.Column(
            "album_order",
            sa.Integer(),
            nullable=False,
            primary_key=False,
            server_default="0",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True, primary_key=False
        ),
        sa.Column("max_downloads", sa.Integer(), nullable=True, primary_key=False),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("user.userid", ondelete="CASCADE"),
            nullable=False,
            primary_key=False,
        ),
    ],
}

INDEXES = {
    "bot_settings": [],
    "broadcast_job": [
        ("ix_broadcast_job_admin_id", ["admin_id"], False),
        ("ix_broadcast_job_admin_id_started_at", ["admin_id", "started_at"], False),
        ("ix_broadcast_job_scheduled_at", ["scheduled_at"], False),
        ("ix_broadcast_job_status", ["status"], False),
        ("ix_broadcast_job_status_scheduled_at", ["status", "scheduled_at"], False),
    ],
    "channel": [
        ("ix_channel_channel_id", ["channel_id"], True),
        ("ix_channel_channel_link", ["channel_link"], False),
        ("ix_channel_is_active", ["is_active"], False),
    ],
    "file_access_log": [
        ("ix_file_access_log_accessed_at", ["accessed_at"], False),
        ("ix_file_access_log_file_code", ["file_code"], False),
        (
            "ix_file_access_log_file_code_accessed_at",
            ["file_code", "accessed_at"],
            False,
        ),
        ("ix_file_access_log_owner_id", ["owner_id"], False),
        ("ix_file_access_log_viewer_id", ["viewer_id"], False),
        (
            "ix_file_access_log_viewer_id_accessed_at",
            ["viewer_id", "accessed_at"],
            False,
        ),
        ("ix_file_access_log_viewer_id_file_code", ["viewer_id", "file_code"], False),
    ],
    "user": [
        ("ix_user_created_at", ["created_at"], False),
        ("ix_user_is_staff", ["is_staff"], False),
        ("ix_user_is_superuser", ["is_superuser"], False),
        ("ix_user_is_superuser_is_staff", ["is_superuser", "is_staff"], False),
        ("ix_user_userid", ["userid"], True),
    ],
    "file": [
        ("ix_file_album_id", ["album_id"], False),
        ("ix_file_album_id_album_order", ["album_id", "album_order"], False),
        ("ix_file_code", ["code"], True),
        ("ix_file_count", ["count"], False),
        ("ix_file_created_at", ["created_at"], False),
        ("ix_file_owner_id_created_at", ["owner_id", "created_at"], False),
        ("ix_file_type", ["type"], False),
        ("ix_file_type_created_at", ["type", "created_at"], False),
    ],
}

ADDITIONS = {"user": {"last_activity_at"}, "file": {"expires_at", "max_downloads"}}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    # Validate every existing table before making any change.
    for name, columns in TABLES.items():
        if name in existing:
            known = {column["name"] for column in inspector.get_columns(name)}
            required = {column.name for column in columns} - ADDITIONS.get(name, set())
            missing = required - known
            if missing:
                raise RuntimeError(
                    f"Unsupported legacy table {name}: missing {sorted(missing)}"
                )
    if "file" in existing:
        owner_keys = [
            key
            for key in inspector.get_foreign_keys("file")
            if key["constrained_columns"] == ["owner_id"]
        ]
        if not owner_keys or any(
            key["referred_table"] != "user" or key["referred_columns"] != ["userid"]
            for key in owner_keys
        ):
            raise RuntimeError(
                "Unsupported legacy file ownership: expected file.owner_id -> user.userid"
            )
    for name, columns in TABLES.items():
        if name not in existing:
            op.create_table(name, *columns)
        else:
            known = {column["name"] for column in sa.inspect(bind).get_columns(name)}
            for column in columns:
                if column.name not in known:
                    op.add_column(name, column)
        inspector = sa.inspect(bind)
        signatures = {
            (tuple(index["column_names"]), bool(index["unique"]))
            for index in inspector.get_indexes(name)
        }
        signatures.update(
            (tuple(constraint["column_names"]), True)
            for constraint in inspector.get_unique_constraints(name)
        )
        for index_name, fields, unique in INDEXES[name]:
            if (tuple(fields), unique) not in signatures:
                op.create_index(index_name, name, fields, unique=unique)
                signatures.add((tuple(fields), unique))


def downgrade():
    raise RuntimeError(
        "This baseline adopts existing data. Restore a database backup to return to Tortoise."
    )
