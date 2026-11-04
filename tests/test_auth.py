from __future__ import annotations

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from src.app.core.auth import load_api_keys
from src.app.routes import proxy as proxy_module
from tests.conftest import TENANT_A_KEY, auth_headers, chat_body, upstream_payload


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


def test_load_api_keys_rejects_duplicate_keys(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "k1:t1,k2:t2,k1:t3")
    with pytest.raises(ValueError, match="entry 3 repeats an API key"):
        load_api_keys()


def test_load_api_keys_rejects_duplicate_keys_for_same_tenant(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "k1:t1,k1:t1")
    with pytest.raises(ValueError, match="repeats an API key"):
        load_api_keys()


def test_load_api_keys_error_does_not_leak_key_values(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "super-secret-key:t1,super-secret-key:t2")
    with pytest.raises(ValueError) as error:
        load_api_keys()
    assert "super-secret-key" not in str(error.value)


def test_load_api_keys_splits_on_first_colon_only(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "k1:team:alpha")
    assert load_api_keys() == {"k1": "team:alpha"}


async def test_malformed_keys_at_request_time_fail_closed(client, monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "malformed")
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers())
    assert response.status_code == 503


async def test_duplicate_keys_at_request_time_fail_closed(client, monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "k1:t1,k1:t2")
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=auth_headers("k1"))
    assert response.status_code == 503


@pytest.fixture
def upstream_ok():
    with respx.mock(assert_all_called=False) as mock:
        mock.post(proxy_module._UPSTREAM_CHAT_URL).mock(
            return_value=httpx.Response(200, json=upstream_payload())
        )
        yield


@pytest.mark.parametrize("flag_value", [None, "", "0", "true", "yes", "11", " 1"])
async def test_legacy_header_is_rejected_when_flag_is_not_exactly_one(
    client, upstream_ok, monkeypatch, flag_value
):
    if flag_value is not None:
        monkeypatch.setenv("GATEWAY_LEGACY_TENANT_HEADER", flag_value)
    with capture_logs() as logs:
        response = await client.post(
            "/v1/chat/completions", json=chat_body(), headers={"X-Tenant-ID": "tenant-a"}
        )
    assert response.status_code == 401
    assert not any(entry["event"] == "legacy_tenant_header_accepted" for entry in logs)


async def test_legacy_header_is_accepted_when_flag_is_one(client, upstream_ok, monkeypatch, fake_session):
    monkeypatch.setenv("GATEWAY_LEGACY_TENANT_HEADER", "1")
    with capture_logs() as logs:
        response = await client.post(
            "/v1/chat/completions", json=chat_body(), headers={"X-Tenant-ID": "tenant-a"}
        )
    assert response.status_code == 200
    assert fake_session.entries[0].tenant_id == "tenant-a"
    warnings = [entry for entry in logs if entry["event"] == "legacy_tenant_header_accepted"]
    assert len(warnings) == 1
    assert warnings[0]["log_level"] == "warning"
    assert warnings[0]["tenant_id"] == "tenant-a"


async def test_legacy_header_with_unknown_tenant_is_rejected(client, monkeypatch):
    monkeypatch.setenv("GATEWAY_LEGACY_TENANT_HEADER", "1")
    response = await client.post(
        "/v1/chat/completions", json=chat_body(), headers={"X-Tenant-ID": "tenant-unknown"}
    )
    assert response.status_code == 401


async def test_legacy_flag_does_not_accept_requests_without_any_identity(client, monkeypatch):
    monkeypatch.setenv("GATEWAY_LEGACY_TENANT_HEADER", "1")
    response = await client.post("/v1/chat/completions", json=chat_body())
    assert response.status_code == 401


async def test_legacy_flag_does_not_bypass_invalid_bearer_token(client, monkeypatch):
    monkeypatch.setenv("GATEWAY_LEGACY_TENANT_HEADER", "1")
    response = await client.post(
        "/v1/chat/completions",
        json=chat_body(),
        headers={**auth_headers("wrong"), "X-Tenant-ID": "tenant-a"},
    )
    assert response.status_code == 401


async def test_valid_bearer_wins_over_legacy_header(client, upstream_ok, monkeypatch, fake_session):
    monkeypatch.setenv("GATEWAY_LEGACY_TENANT_HEADER", "1")
    response = await client.post(
        "/v1/chat/completions",
        json=chat_body(),
        headers={**auth_headers(TENANT_A_KEY), "X-Tenant-ID": "tenant-b"},
    )
    assert response.status_code == 200
    assert fake_session.entries[0].tenant_id == "tenant-a"


async def test_legacy_header_is_accepted_on_quota_status(client, monkeypatch):
    monkeypatch.setenv("GATEWAY_LEGACY_TENANT_HEADER", "1")
    response = await client.get("/quota/tenant-a", headers={"X-Tenant-ID": "tenant-a"})
    assert response.status_code == 200
