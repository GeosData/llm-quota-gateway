from __future__ import annotations

import hmac
import os

import structlog
from fastapi import Header, HTTPException

logger = structlog.get_logger(__name__)

LEGACY_TENANT_HEADER_FLAG = "GATEWAY_LEGACY_TENANT_HEADER"


def load_api_keys() -> dict[str, str]:
    raw = os.environ.get("GATEWAY_API_KEYS", "")
    keys: dict[str, str] = {}
    for position, entry in enumerate(raw.split(","), start=1):
        entry = entry.strip()
        if not entry:
            continue
        api_key, separator, tenant_id = entry.partition(":")
        if not separator or not api_key or not tenant_id:
            raise ValueError(f"GATEWAY_API_KEYS entry {position} must look like <api_key>:<tenant_id>")
        if api_key in keys:
            raise ValueError(f"GATEWAY_API_KEYS entry {position} repeats an API key already defined earlier")
        keys[api_key] = tenant_id
    return keys


def require_api_keys() -> dict[str, str]:
    keys = load_api_keys()
    if not keys:
        raise ValueError("GATEWAY_API_KEYS is missing or empty; set it to <api_key>:<tenant_id>[,...]")
    return keys


def _legacy_tenant_header_enabled() -> bool:
    return os.environ.get(LEGACY_TENANT_HEADER_FLAG) == "1"


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def authenticate_tenant(
    authorization: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> str:
    try:
        keys = require_api_keys()
    except ValueError as exc:
        logger.error("auth_config_invalid", reason=str(exc))
        raise HTTPException(status_code=503, detail={"error": "auth_not_configured"}) from exc

    token = _extract_bearer_token(authorization)
    if token is None:
        if _legacy_tenant_header_enabled() and x_tenant_id and x_tenant_id in set(keys.values()):
            logger.warning("legacy_tenant_header_accepted", tenant_id=x_tenant_id)
            return x_tenant_id
        raise HTTPException(
            status_code=401,
            detail={"error": "missing_or_malformed_credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    matched_tenant: str | None = None
    for api_key, tenant_id in keys.items():
        if hmac.compare_digest(api_key.encode(), token.encode()):
            matched_tenant = tenant_id

    if matched_tenant is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_api_key"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return matched_tenant
