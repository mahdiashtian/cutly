"""Bot configuration management."""

from __future__ import annotations

from decouple import config

# Bot Configuration
ADMIN_MASTER: int = int(config("ADMIN_MASTER", default="1017215648"))
API_ID: int = int(config("API_ID"))
API_HASH: str = config("API_HASH")
BOT_TOKEN: str = config("BOT_TOKEN")
SESSION_STRING: str = config("SESSION_STRING", default="")
SESSION_NAME: str = config("SESSION_NAME", default="cutly")
WORKERS: int = int(config("WORKERS", default="20"))

# Database Configuration
DB_NAME: str = config("DB_NAME", default="")
DB_USER: str = config("DB_USER", default="")
DB_PASSWORD: str = config("DB_PASSWORD", default="")
DB_HOST: str = config("DB_HOST", default="localhost")
DB_PORT: str = config("DB_PORT", default="5432")
DB_URL_OVERRIDE: str = config("DB_URL", default="")

