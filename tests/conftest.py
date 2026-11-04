from __future__ import annotations

import json
import os
import sys
import types

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("OPENAI_API_KEY", "upstream-test-key")
os.environ.setdefault("DEFAULT_QUOTA_LIMIT", "1000")

fastembed_stub = types.ModuleType("fastembed")
fastembed_stub.TextEmbedding = object
sys.modules.setdefault("fastembed", fastembed_stub)

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio

from src.app.core import quota as quota_module
from src.app.db.session import get_session
from src.app.main import app
from src.app.routes import proxy as proxy_module
from src.app.routes import quota as quota_route_module

TENANT_A_KEY = "key-tenant-a"
TENANT_B_KEY = "key-tenant-b"


class FakeSession:
    def __init__(self) -> None:
        self.entries: list = []

    def add(self, entry) -> None:
        self.entries.append(entry)

    async def commit(self) -> None:
        return None


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.fail_on_set = False

    async def get(self, prompt: str, tenant_id: str) -> str | None:
        return self.store.get((tenant_id, prompt))

    async def set(self, prompt: str, response: str, tenant_id: str) -> None:
        if self.fail_on_set:
            raise RuntimeError("cache unavailable")
        self.store[(tenant_id, prompt)] = response


def upstream_payload(prompt_tokens: int = 10, completion_tokens: int = 5) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@pytest.fixture(autouse=True)
def gateway_api_keys(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", f"{TENANT_A_KEY}:tenant-a,{TENANT_B_KEY}:tenant-b")


@pytest.fixture(autouse=True)
def quota_limit(monkeypatch):
    monkeypatch.setattr(proxy_module, "_DEFAULT_QUOTA_LIMIT", 1000)
    monkeypatch.setattr(quota_route_module, "_DEFAULT_QUOTA_LIMIT", 1000)


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await quota_module.load_lua_script(client)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def fake_cache():
    return FakeCache()


@pytest_asyncio.fixture
async def client(redis_client, fake_cache, fake_session):
    app.state.redis = redis_client
    app.state.semantic_cache = fake_cache
    app.dependency_overrides[get_session] = lambda: fake_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as http_client:
        yield http_client
    app.dependency_overrides.clear()


def auth_headers(api_key: str = TENANT_A_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def chat_body(content: str = "hello world", **extra) -> dict:
    return {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": content}], **extra}


def serialized(payload: dict) -> str:
    return json.dumps(payload)
