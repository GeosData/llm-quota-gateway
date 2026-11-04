from __future__ import annotations

import asyncio

import pytest

from src.app.core import quota as quota_module
from src.app.core.quota import check_and_consume, get_quota_status


async def test_consumes_tokens_within_limit(redis_client):
    allowed, remaining, ttl = await check_and_consume(redis_client, "t", 300, 1000, 60)
    assert (allowed, remaining) == (True, 700)
    assert 0 < ttl <= 60


async def test_allows_request_that_exactly_reaches_limit(redis_client):
    allowed, remaining, _ = await check_and_consume(redis_client, "t", 1000, 1000, 60)
    assert (allowed, remaining) == (True, 0)


async def test_denies_request_exceeding_limit_without_consuming(redis_client):
    await check_and_consume(redis_client, "t", 900, 1000, 60)
    allowed, remaining, _ = await check_and_consume(redis_client, "t", 200, 1000, 60)
    assert (allowed, remaining) == (False, 100)
    used, _, _ = await get_quota_status(redis_client, "t", 1000)
    assert used == 900


async def test_tenants_have_independent_budgets(redis_client):
    await check_and_consume(redis_client, "a", 1000, 1000, 60)
    allowed, _, _ = await check_and_consume(redis_client, "b", 500, 1000, 60)
    assert allowed is True


async def test_window_expiry_resets_budget(redis_client):
    await check_and_consume(redis_client, "t", 1000, 1000, 60)
    await redis_client.delete("quota:t")
    allowed, remaining, _ = await check_and_consume(redis_client, "t", 100, 1000, 60)
    assert (allowed, remaining) == (True, 900)


async def test_ttl_is_set_only_once_per_window(redis_client):
    await check_and_consume(redis_client, "t", 10, 1000, 60)
    await redis_client.expire("quota:t", 30)
    _, _, ttl = await check_and_consume(redis_client, "t", 10, 1000, 60)
    assert ttl <= 30


async def test_concurrent_requests_never_exceed_limit(redis_client):
    results = await asyncio.gather(*[check_and_consume(redis_client, "t", 100, 1000, 60) for _ in range(30)])
    assert sum(1 for allowed, _, _ in results if allowed) == 10
    used, _, _ = await get_quota_status(redis_client, "t", 1000)
    assert used == 1000


async def test_check_and_consume_requires_loaded_script(redis_client, monkeypatch):
    monkeypatch.setattr(quota_module, "_script_sha", None)
    with pytest.raises(RuntimeError):
        await check_and_consume(redis_client, "t", 1, 10, 60)


async def test_quota_status_for_unknown_tenant_is_empty(redis_client):
    assert await get_quota_status(redis_client, "ghost", 1000) == (0, 1000, 0)


async def test_quota_status_remaining_never_negative(redis_client):
    await redis_client.set("quota:t", 5000)
    used, remaining, _ = await get_quota_status(redis_client, "t", 1000)
    assert (used, remaining) == (5000, 0)
