from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from app.factory import BotFactory
from core.database import database_url


@pytest.mark.parametrize(
    "input_url,expected",
    [
        ("sqlite://db.sqlite3", "sqlite+aiosqlite:///db.sqlite3"),
        ("sqlite://:memory:", "sqlite+aiosqlite:///:memory:"),
        ("sqlite:///relative.db", "sqlite+aiosqlite:///relative.db"),
        (
            "postgres://u:p@localhost:5432/cutly",
            "postgresql+asyncpg://u:p@localhost:5432/cutly",
        ),
        (
            "postgresql+asyncpg://u:p@localhost/cutly",
            "postgresql+asyncpg://u:p@localhost/cutly",
        ),
    ],
)
def test_database_url_compatibility(monkeypatch, input_url, expected):
    monkeypatch.setenv("DB_URL", input_url)
    from sqlalchemy import make_url

    assert database_url() == make_url(expected)


def test_database_credentials_are_escaped(monkeypatch):
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("DB_NAME", "cutly")
    monkeypatch.setenv("DB_USER", "user")
    monkeypatch.setenv("DB_PASSWORD", "p@ss:/#%")
    assert database_url().password == "p@ss:/#%"


@pytest.mark.parametrize("string_session", [False, True])
def test_real_telethon_factory_both_session_modes(
    monkeypatch, tmp_path, string_session
):
    from app import factory as module
    from telethon import TelegramClient

    if not string_session:
        monkeypatch.setattr(module, "SESSION_STRING", "")
        monkeypatch.setattr(module, "SESSION_NAME", str(tmp_path / "test"))
    factory = BotFactory()
    client = factory.create_client()
    assert isinstance(client, TelegramClient)
    assert client is factory.create_client()
    assert factory.create_scheduler() is factory.create_scheduler()
    client.session.close()


async def test_startup_failure_still_releases_resources(app, telegram, monkeypatch):
    cache = SimpleNamespace(connect=AsyncMock(return_value=False), close=AsyncMock())
    from core import cache as module

    monkeypatch.setattr(module, "get_cache", lambda: cache)
    init = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(app, "init_db", init)
    monkeypatch.setattr(app, "close_db", close)
    monkeypatch.setattr(app, "userid_list", AsyncMock(return_value=[]))
    telegram.start.side_effect = RuntimeError("authentication failed")
    with pytest.raises(RuntimeError, match="authentication failed"):
        await app.main()
    telegram.disconnect.assert_awaited_once()
    cache.close.assert_awaited_once()
    close.assert_awaited_once()


async def test_database_closes_if_cache_shutdown_fails(app, telegram, monkeypatch):
    cache = SimpleNamespace(
        connect=AsyncMock(side_effect=RuntimeError("startup")),
        close=AsyncMock(side_effect=RuntimeError("cache close")),
    )
    from core import cache as module

    monkeypatch.setattr(module, "get_cache", lambda: cache)
    monkeypatch.setattr(app, "init_db", AsyncMock())
    close = AsyncMock()
    monkeypatch.setattr(app, "close_db", close)
    with pytest.raises(RuntimeError):
        await app.main()
    close.assert_awaited_once()
