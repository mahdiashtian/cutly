# Cutly — Telegram File Storage Bot

An async Telegram bot for storing and sharing files, built with **Telethon 1.45.0**, **SQLAlchemy 2.0.54**, **Alembic 1.20.0**, and **Redis**.

The migration preserves existing Persian menus, user/admin workflows, file links and database rows. [Feature contracts](docs/features.md) record behavior and regression tests. [Migration instructions](docs/migration.md) cover existing deployments and rollback.

## Features

- Single files and multi-file upload sessions with one share link.
- Direct Telegram media identifiers, ordered albums and upload history.
- Passwords, custom/global captions and caption visibility controls.
- Link expiry, download caps, counters and temporary message cleanup.
- Admin permissions and mandatory channel membership.
- Copy/forward broadcasts, audience selection, previews, Tehran-time scheduling, cancellation and CSV reports.
- Dashboard statistics and paginated unique-link access logs.
- Persistent Redis caching with database fallback.
- Full PostgreSQL database dumps, portable data-only backups, and confirmed atomic restores.

## Setup

Use Python 3.10 or newer. SQLite works by default; PostgreSQL and Redis are supported. Redis can be disabled for development, and failed cache connections fall back to database reads.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
```

Copy [.env.example](.env.example) to .env and configure API_ID, API_HASH, BOT_TOKEN, ADMIN_MASTER and STORAGE_CHANNEL_ID. Keep existing sessions and credentials when upgrading. uvloop is installed on supported Unix platforms; Windows uses asyncio.

```bash
python -m alembic upgrade head
python main.py
```

Startup also upgrades the schema through Alembic. Existing SQLite and PostgreSQL DB_URL values are accepted along with SQLAlchemy async DSNs. Existing DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT settings remain supported when DB_URL is empty.

## Structure

```text
app/          configuration, client factory and dependency container
core/         SQLAlchemy models, sessions, Redis, conversation and upload state
services/     repositories and business operations
utils/        Telethon filters, delivery, keyboards and Persian messages
migrations/   frozen Alembic revisions and async migration environment
tests/        regression tests, legacy contracts and optional integration checks
docs/         feature inventory and migration guide
main.py       event handlers and application lifecycle
```

Each database operation receives its own async session. Conversation updates write only changed fields, albums commit together, and counters use atomic SQL updates. Redis uses an atomic user ID index, targeted profile invalidation, and expiring versioned snapshots. Existing JSON user lists migrate on their next insertion.

File and album metadata and settings use versioned Redis snapshots. Download counts remain authoritative in SQL; concurrent requests reserve download slots atomically. Expired Telegram file references are refreshed from the storage channel. See [backup and recovery](docs/backup-restore.md) for supported formats, version compatibility, and operational limits.

Cold reads share a loader per key, background work uses bounded worker counts, and connection pools are configurable. See [performance and cache design](docs/performance.md) and the [verification record](docs/verification.md) for concurrency limits and measured test results.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
```

Integration tests require disposable PostgreSQL/Redis URLs; see the [verification guide](docs/migration.md#verification). Unit tests never connect to Telegram. Scheduled broadcasts and unfinished conversations remain in memory as in the original application.

## License

[MIT](LICENSE).
