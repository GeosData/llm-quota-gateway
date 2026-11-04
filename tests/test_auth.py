from __future__ import annotations

import pytest

from src.app.core.auth import load_api_keys
from tests.conftest import TENANT_A_KEY, auth_headers, chat_body


async def test_chat_without_credentials_is_rejected(client):
    response = await client.post("/v1/chat/completions", json=chat_body())
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_chat_with_unknown_key_is_rejected(client):
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers("nope"))
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "invalid_api_key"


async def test_chat_with_non_bearer_scheme_is_rejected(client):
    response = await client.post(
        "/v1/chat/completions", json=chat_body(), headers={"Authorization": f"Basic {TENANT_A_KEY}"}
    )
    assert response.status_code == 401


async def test_chat_with_empty_bearer_token_is_rejected(client):
    response = await client.post(
        "/v1/chat/completions", json=chat_body(), headers={"Authorization": "Bearer "}
    )
    assert response.status_code == 401


async def test_tenant_header_alone_does_not_authenticate(client):
    response = await client.post(
        "/v1/chat/completions", json=chat_body(), headers={"X-Tenant-ID": "tenant-a"}
    )
    assert response.status_code == 401


async def test_auth_fails_closed_when_no_keys_configured(client, monkeypatch):
    monkeypatch.delenv("GATEWAY_API_KEYS")
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "auth_not_configured"


async def test_quota_status_requires_credentials(client):
    response = await client.get("/quota/tenant-a")
    assert response.status_code == 401


async def test_quota_status_of_another_tenant_is_forbidden(client):
    response = await client.get("/quota/tenant-b", headers=auth_headers(TENANT_A_KEY))
    assert response.status_code == 403


async def test_quota_status_for_own_tenant_succeeds(client):
    response = await client.get("/quota/tenant-a", headers=auth_headers(TENANT_A_KEY))
    assert response.status_code == 200
    assert response.json()["used_tokens"] == 0


async def test_health_is_public(client):
    response = await client.get("/health")
    assert response.status_code == 200


def test_load_api_keys_parses_entries(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", " k1:t1 , k2:t2 ,")
    assert load_api_keys() == {"k1": "t1", "k2": "t2"}


@pytest.mark.parametrize("raw", ["justakey", ":tenant", "key:"])
def test_load_api_keys_rejects_malformed_entries(monkeypatch, raw):
    monkeypatch.setenv("GATEWAY_API_KEYS", raw)
    with pytest.raises(ValueError):
        load_api_keys()
