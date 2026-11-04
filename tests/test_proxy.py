from __future__ import annotations

import httpx
import pytest
import respx

from src.app.routes import proxy as proxy_module
from tests.conftest import (
    TENANT_B_KEY,
    auth_headers,
    chat_body,
    serialized,
    upstream_payload,
)


@pytest.fixture
def upstream():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(proxy_module._UPSTREAM_CHAT_URL)
        route.mock(return_value=httpx.Response(200, json=upstream_payload()))
        yield route


async def test_cache_miss_forwards_to_upstream_and_audits(client, upstream, fake_session, fake_cache):
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["x-cache"] == "MISS"
    assert upstream.call_count == 1
    assert upstream.calls.last.request.headers["authorization"] == "Bearer upstream-test-key"
    assert len(fake_session.entries) == 1
    assert fake_session.entries[0].tenant_id == "tenant-a"
    assert fake_session.entries[0].cached is False
    assert ("tenant-a", "hello world") in fake_cache.store


async def test_cache_hit_skips_upstream_and_quota(client, upstream, fake_cache, fake_session, redis_client):
    fake_cache.store[("tenant-a", "hello world")] = serialized(upstream_payload())
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["x-cache"] == "HIT"
    assert upstream.call_count == 0
    assert fake_session.entries[0].cached is True
    assert await redis_client.get("quota:tenant-a") is None


async def test_cache_is_isolated_between_tenants(client, upstream, fake_cache):
    fake_cache.store[("tenant-a", "hello world")] = serialized(upstream_payload())
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers(TENANT_B_KEY))
    assert response.headers["x-cache"] == "MISS"
    assert upstream.call_count == 1


async def test_quota_is_consumed_from_estimate(client, upstream, redis_client):
    await client.post(
        "/v1/chat/completions", json=chat_body("x" * 400, max_tokens=50), headers=auth_headers()
    )
    assert int(await redis_client.get("quota:tenant-a")) == 100 + 50


async def test_default_max_tokens_is_used_for_estimate(client, upstream, redis_client):
    await client.post("/v1/chat/completions", json=chat_body("x" * 40), headers=auth_headers())
    assert int(await redis_client.get("quota:tenant-a")) == 10 + 200


async def test_over_quota_returns_429_with_retry_after(client, upstream, redis_client):
    await redis_client.set("quota:tenant-a", 990)
    await redis_client.expire("quota:tenant-a", 120)
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 429
    assert response.json()["detail"]["error"] == "quota_exceeded"
    assert 0 < int(response.headers["retry-after"]) <= 120
    assert upstream.call_count == 0


async def test_one_tenant_exhausting_quota_does_not_block_another(client, upstream, redis_client):
    await redis_client.set("quota:tenant-a", 1000)
    blocked = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    allowed = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers(TENANT_B_KEY))
    assert blocked.status_code == 429
    assert allowed.status_code == 200


async def test_quota_status_reflects_consumption(client, upstream):
    await client.post("/v1/chat/completions", json=chat_body("x" * 40, max_tokens=10), headers=auth_headers())
    response = await client.get("/quota/tenant-a", headers=auth_headers())
    body = response.json()
    assert body["used_tokens"] == 20
    assert body["remaining"] == 980
    assert body["limit"] == 1000


async def test_quota_status_without_redis_returns_503(client):
    from src.app.main import app

    app.state.redis = None
    response = await client.get("/quota/tenant-a", headers=auth_headers())
    assert response.status_code == 503


async def test_quota_not_enforced_without_redis(client, upstream):
    from src.app.main import app

    app.state.redis = None
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 200


@pytest.mark.parametrize("max_tokens", [0, -5])
async def test_non_positive_max_tokens_is_rejected(client, upstream, redis_client, max_tokens):
    response = await client.post(
        "/v1/chat/completions", json=chat_body(max_tokens=max_tokens), headers=auth_headers()
    )
    assert response.status_code == 422
    assert await redis_client.get("quota:tenant-a") is None


async def test_invalid_body_returns_422(client, upstream):
    response = await client.post(
        "/v1/chat/completions", json={"model": "gpt-4o-mini"}, headers=auth_headers()
    )
    assert response.status_code == 422


async def test_unknown_role_returns_422(client, upstream):
    body = {"model": "m", "messages": [{"role": "root", "content": "x"}]}
    response = await client.post("/v1/chat/completions", json=body, headers=auth_headers())
    assert response.status_code == 422


async def test_upstream_error_status_is_propagated(client, upstream, fake_session):
    upstream.mock(return_value=httpx.Response(500, json={"error": "boom"}))
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 500
    assert response.json()["detail"] == {"error": "boom"}
    assert fake_session.entries == []


async def test_upstream_non_json_error_is_propagated(client, upstream):
    upstream.mock(return_value=httpx.Response(502, text="bad gateway"))
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 502
    assert response.json()["detail"] == "bad gateway"


async def test_cache_store_failure_does_not_fail_request(client, upstream, fake_cache):
    fake_cache.fail_on_set = True
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["x-cache"] == "MISS"


async def test_list_content_blocks_are_used_as_prompt(client, upstream, fake_cache):
    body = {
        "model": "m",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "describe"}, {"type": "image_url"}]}
        ],
    }
    await client.post("/v1/chat/completions", json=body, headers=auth_headers())
    assert ("tenant-a", "describe") in fake_cache.store


async def test_upstream_api_key_prefers_llm_api_key(client, upstream, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "override-key")
    await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert upstream.calls.last.request.headers["authorization"] == "Bearer override-key"
