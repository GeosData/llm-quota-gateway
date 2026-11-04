from __future__ import annotations

import pytest

from src.app import main as main_module
from src.app.main import app


class StartupReachedDatabase(Exception):
    pass


@pytest.fixture
def failing_database(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    async def refuse_pool(*args, **kwargs):
        raise StartupReachedDatabase

    monkeypatch.setattr(main_module.asyncpg, "create_pool", refuse_pool)


async def run_lifespan():
    async with app.router.lifespan_context(app):
        pass


async def test_startup_aborts_when_keys_are_missing(failing_database, monkeypatch):
    monkeypatch.delenv("GATEWAY_API_KEYS")
    with pytest.raises(ValueError, match="GATEWAY_API_KEYS is missing or empty"):
        await run_lifespan()


@pytest.mark.parametrize("raw", ["", "   ", ",,,"])
async def test_startup_aborts_when_keys_are_empty(failing_database, monkeypatch, raw):
    monkeypatch.setenv("GATEWAY_API_KEYS", raw)
    with pytest.raises(ValueError, match="GATEWAY_API_KEYS is missing or empty"):
        await run_lifespan()


@pytest.mark.parametrize("raw", ["justakey", ":tenant", "key:", "k1:t1,broken"])
async def test_startup_aborts_when_keys_are_malformed(failing_database, monkeypatch, raw):
    monkeypatch.setenv("GATEWAY_API_KEYS", raw)
    with pytest.raises(ValueError, match="must look like"):
        await run_lifespan()


async def test_startup_aborts_when_keys_are_duplicated(failing_database, monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "k1:t1,k1:t2")
    with pytest.raises(ValueError, match="repeats an API key"):
        await run_lifespan()


async def test_startup_proceeds_past_validation_with_valid_keys(failing_database):
    with pytest.raises(StartupReachedDatabase):
        await run_lifespan()
