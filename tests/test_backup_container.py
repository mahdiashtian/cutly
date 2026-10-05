from unittest.mock import AsyncMock
import pytest
from core.cache import RedisCache
from services import backup


async def test_postgres_backup_uses_effective_dsn_and_argument_list(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_URL", "postgresql://user:p%40ss@localhost:5544/cutly")
    monkeypatch.setenv("PG_DUMP_PATH", "pg_dump")
    process = AsyncMock()
    process.returncode = 0
    launch = AsyncMock(return_value=process)
    monkeypatch.setattr(backup.asyncio, "create_subprocess_exec", launch)
    path = await backup.create_backup()
    assert path.startswith(str(tmp_path)) and path.endswith(".sql")
    args, kwargs = launch.call_args
    assert args[:7] == ("pg_dump", "-U", "user", "-h", "localhost", "-p", "5544")
    assert args[-1] == "cutly" and kwargs["env"]["PGPASSWORD"] == "p@ss"
    process.communicate.assert_awaited_once()


async def test_backup_failure_and_sqlite_behavior(monkeypatch):
    assert await backup.create_backup() is None
    monkeypatch.setenv("DB_URL", "postgresql://user@localhost/cutly")
    monkeypatch.setenv("PG_DUMP_PATH", "pg_dump")
    monkeypatch.setattr(
        backup.asyncio,
        "create_subprocess_exec",
        AsyncMock(side_effect=OSError("missing pg_dump")),
    )
    assert await backup.create_backup() is None


def test_dependency_container_registers_redis_and_repositories(isolated_db):
    from app.container import get_container, setup_container
    from services.file_repository import FileRepository
    from services.user_repository import UserRepository

    container = get_container()
    container.reset()
    setup_container()
    assert isinstance(container.resolve("cache"), RedisCache)
    assert container.resolve("cache") is isolated_db
    assert isinstance(container.resolve("file_repository"), FileRepository)
    assert isinstance(container.resolve("user_repository"), UserRepository)
    assert container.resolve("file_repository") is container.resolve("file_repository")
    assert container.has("cache")
    with pytest.raises(KeyError):
        container.resolve("missing")
    container.reset()
