"""Injected sync connection at startup, async SQLAlchemy from CLI."""

import asyncio
from alembic import context
import sqlalchemy as sa
from core.database import create_engine, database_url
from core.models import Base, UTCDateTime

config = context.config
model_metadata = Base.metadata


def migrate(connection):
    target_metadata = sa.MetaData()
    for table in model_metadata.sorted_tables:
        table.to_metadata(target_metadata)
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names())
    signatures = {}
    foreign_keys = {}
    for name in existing & set(target_metadata.tables):
        if (
            connection.dialect.supports_comments
            and target_metadata.tables[name].comment is None
        ):
            target_metadata.tables[name].comment = inspector.get_table_comment(name)[
                "text"
            ]
        signatures[name] = {
            (tuple(item["column_names"]), bool(item["unique"]))
            for item in inspector.get_indexes(name)
        }
        signatures[name].update(
            (tuple(item["column_names"]), True)
            for item in inspector.get_unique_constraints(name)
        )
        foreign_keys[name] = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
                item["options"].get("ondelete", "NO ACTION").upper(),
            )
            for item in inspector.get_foreign_keys(name)
        }
        if connection.dialect.name == "sqlite":
            # SQLite reflection can omit ON DELETE on Tortoise inline REFERENCES.
            quoted = connection.dialect.identifier_preparer.quote(name)
            rows = (
                connection.exec_driver_sql(f"PRAGMA foreign_key_list({quoted})")
                .mappings()
                .all()
            )
            groups = {}
            for row in rows:
                groups.setdefault(row["id"], []).append(row)
            foreign_keys[name] = {
                (
                    tuple(
                        row["from"] for row in sorted(group, key=lambda row: row["seq"])
                    ),
                    group[0]["table"],
                    tuple(
                        row["to"] for row in sorted(group, key=lambda row: row["seq"])
                    ),
                    group[0]["on_delete"].upper(),
                )
                for group in groups.values()
            }

    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == "table" and reflected and name == "aerich":
            return False
        if type_ in ("index", "unique_constraint") and compare_to is None:
            table = obj.table.name
            signature = (
                tuple(column.name for column in obj.columns),
                type_ == "unique_constraint" or bool(obj.unique),
            )
            if not reflected and signature in signatures.get(table, set()):
                return False
            if reflected and table in target_metadata.tables:
                mapped = target_metadata.tables[table]
                expected = {
                    (tuple(column.name for column in index.columns), bool(index.unique))
                    for index in mapped.indexes
                }
                expected.update(
                    (tuple(column.name for column in constraint.columns), True)
                    for constraint in mapped.constraints
                    if isinstance(constraint, sa.UniqueConstraint)
                )
                if signature in expected or (
                    name
                    and name.startswith("idx_")
                    and (signature[0], True) in expected
                ):
                    return False
        if (
            connection.dialect.name == "sqlite"
            and type_ == "foreign_key_constraint"
            and compare_to is None
        ):
            mapped = target_metadata.tables.get(obj.table.name)
            if mapped is not None:
                for constraint in mapped.foreign_key_constraints:
                    signature = (
                        tuple(item.parent.name for item in constraint.elements),
                        constraint.elements[0].column.table.name,
                        tuple(item.column.name for item in constraint.elements),
                        (constraint.ondelete or "NO ACTION").upper(),
                    )
                    if (
                        signature in foreign_keys.get(obj.table.name, set())
                        and constraint.onupdate is None
                    ):
                        fields = tuple(item.parent.name for item in obj.elements)
                        targets = tuple(item.column.name for item in obj.elements)
                        if (
                            fields == signature[0]
                            and targets == signature[2]
                            and obj.elements[0].column.table.name == signature[1]
                        ):
                            return False
        return True

    def compare_type(
        ctx, inspected_column, metadata_column, inspected_type, metadata_type
    ):
        if connection.dialect.name == "sqlite":
            if isinstance(metadata_type, UTCDateTime) and isinstance(
                inspected_type, sa.DateTime
            ):
                return False
            if isinstance(metadata_type, sa.Boolean) and isinstance(
                inspected_type, sa.Integer
            ):
                return False
        return None

    def render_item(type_, obj, autogen_context):
        if type_ == "type" and isinstance(obj, UTCDateTime):
            return "sa.DateTime(timezone=True)"
        return False

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=compare_type,
        include_object=include_object,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async():
    engine = create_engine(database_url())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError(
        "This baseline inspects tables; run against a database, without --sql."
    )
elif config.attributes.get("connection") is not None:
    migrate(config.attributes["connection"])
else:
    asyncio.run(run_async())
