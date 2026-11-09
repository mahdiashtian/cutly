# Cutly — Telegram file storage bot

Upload files (single or albums) to the bot and get one share link. Links can have
a password, a caption, an expiry date and a download cap. Admins get mandatory
channel membership, a global caption, scheduled broadcasts, statistics, per-user
access logs, and backup/restore — all from inside Telegram.

**Stack:** Telethon 1.45 · SQLAlchemy 2 (async) · Alembic · PostgreSQL · Redis ·
Celery + Celery Beat · Pydantic.

The design (layers, cache, database, background jobs) and the reasons behind
each decision are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run

Requirements: Python 3.11+ and Docker.

```bash
cp .env.example .env          # fill in API_ID, API_HASH, BOT_TOKEN, ADMIN_MASTER, STORAGE_CHANNEL_ID
docker compose up -d          # PostgreSQL + Redis (cache) + Redis (state)
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

`python main.py` upgrades the database schema, starts the Celery worker and beat
processes, and runs the bot; Ctrl+C stops all of them.

The Docker services listen on localhost only, on fixed ports that avoid the
usual defaults:

| Service | Port | Used by |
| --- | --- | --- |
| postgres | 25432 | `DB_URL` |
| redis-cache | 26379 | `REDIS_CACHE_URL` |
| redis-state | 26380 | `REDIS_STATE_URL` (also the Celery queue) |

To run the background processes yourself (for example on other machines), set
`EMBEDDED_WORKERS=false` and start them with the commands in `worker/app.py`.

The full database backup in the admin panel uses `pg_dump`; install the
PostgreSQL 17 client tools on the host or set `PG_DUMP_PATH`. The data-only
backup needs nothing extra.

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
