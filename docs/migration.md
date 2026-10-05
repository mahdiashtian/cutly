# Database migration and rollback

The rewrite uses Telethon 1.45.0, SQLAlchemy 2.0.54 and Alembic 1.20.0. Redis remains the application cache. Python 3.10 or newer is required.

## Existing deployment

1. Stop the old bot process.
2. Back up the database and retain the original source and environment. For SQLite, use its backup API or copy the database while all writers are stopped. For PostgreSQL, use pg_dump.
3. Install requirements.txt in the deployment environment.
4. Keep existing Telegram credentials, session, storage channel and Redis settings.
5. Run python -m alembic upgrade head against the existing DB_URL, then python main.py.

Startup also invokes Alembic upgrade head on the application's database connection. A separate upgrade step makes the database change reviewable before the bot starts.

The baseline creates missing tables, adds last_activity_at/expires_at/max_downloads to earlier schemas, and preserves existing rows and sequences. It verifies required column names before making changes and rejects an incompatible table. It preserves the file.owner_id → user.userid relationship and cascade deletion.

Both legacy DSNs (sqlite://db.sqlite3, postgres://...) and SQLAlchemy async DSNs are supported. DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT remain available when DB_URL is empty. Alembic needs only database configuration; it does not require Telegram credentials.

## Future schema changes

Change the SQLAlchemy mappings, then run:

~~~bash
python -m alembic revision --autogenerate -m "Describe the schema change"
python -m alembic upgrade head
python -m alembic check
~~~

Review generated migrations before applying them. The baseline is frozen and never imports current model definitions. The environment recognizes equivalent legacy index names, SQLite integer booleans and timestamp representations. UTCDateTime is rendered as a standard SQLAlchemy DateTime in generated revisions. No-op checks cover fresh and adopted SQLite databases.

This baseline inspects the target schema; offline --sql execution is unsupported.

## Rollback

The migration baseline refuses downgrade rather than dropping adopted user data. To restore the old application, stop the bot, restore the database snapshot and the saved original source/environment, then restart. Future revisions can define their own downgrade steps.

The local source backup created during this rewrite is in .migration-backup/20261005-original. It includes the user's uncommitted album-caption change. No production database or Telegram session was modified during verification.

## Verification

~~~bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
~~~

Tests use isolated SQLite databases, FakeRedis and Telegram doubles. The contract scenario compares public-service results with the original implementation. Legacy fixtures exercise schema adoption, row preservation, sequences and rejected schemas.

Optional integration tests use disposable services:

~~~powershell
$env:CUTLY_TEST_POSTGRES_URL = "postgresql://test_user@localhost:15432/postgres"
$env:CUTLY_TEST_REDIS_URL = "redis://localhost:16379/0"
python -m pytest tests/test_integration.py -q
~~~

The PostgreSQL user must be allowed to create databases; each test creates and drops only its uniquely named database. Use a dedicated Redis instance: integration tests operate on the actual cutly:* cache keys. These are test service settings, never production DSNs.

Live Telegram authentication and message delivery require deployment credentials and a test storage channel. Automated tests use actual Telethon types and event registrations with mocked network calls.
