# Cutly — Telegram file storage bot

Upload files (single or albums) to the bot and get one share link. Links can have
a password, a caption, an expiry date and a download cap. Admins get mandatory
channel membership, a global caption, scheduled broadcasts, statistics, per-user
access logs, and backup/restore — all from inside Telegram.

**Stack:** Telethon 1.45 · SQLAlchemy 2 (async) · Alembic · PostgreSQL · Redis ·
Celery + Celery Beat · Pydantic.

The design (layers, cache, database, background jobs) and the reasons behind
each decision are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Processes

| Process | Command | Role |
| --- | --- | --- |
| migrate | `alembic upgrade head` | Run once per deploy, before the others |
| bot | `python main.py` | Answers Telegram updates; never does long work itself |
| worker | `celery -A worker.app worker -Q default,broadcasts -c 4` | Broadcasts, message auto-delete, backups, restores |
| beat | `celery -A worker.app beat` | Starts scheduled broadcasts, cleans temp files, refreshes channel titles |

## Run with Docker

```bash
cp .env.example .env   # fill in API_ID, API_HASH, BOT_TOKEN, ADMIN_MASTER, STORAGE_CHANNEL_ID
docker compose up -d --build
```

## Run locally

Python 3.11+, PostgreSQL and Redis.

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
python main.py
celery -A worker.app worker -Q default,broadcasts -c 4 --loglevel=INFO   # second terminal
celery -A worker.app beat --loglevel=INFO                               # third terminal
```

On Windows add `--pool=solo` to the worker (Celery's prefork pool is POSIX only).

## Upgrading from the previous release

`alembic upgrade head` converts the old tables in place (users, files, albums,
access logs, channels, broadcast history, settings); plain-text link passwords are
hashed on the way. Take a backup first — the conversion has no downgrade. Old
`.jsonl.gz` data backups can still be restored from the admin panel.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

Tests run on in-memory SQLite and fakeredis, with Telegram faked. To also run the
PostgreSQL suite, point `CUTLY_TEST_POSTGRES_URL` at an empty, disposable
database (`postgresql+asyncpg://…`); it drops and recreates the `public` schema.

## License

[MIT](LICENSE)
