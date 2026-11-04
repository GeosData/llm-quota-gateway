from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def load_api_keys() -> dict[str, str]:
    raw = os.environ.get("GATEWAY_API_KEYS", "")
    keys: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        api_key, separator, tenant_id = entry.partition(":")
        if not separator or not api_key or not tenant_id:
            raise ValueError("GATEWAY_API_KEYS entries must look like <api_key>:<tenant_id>")
        keys[api_key] = tenant_id
    return keys


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def authenticate_tenant(authorization: str | None = Header(default=None)) -> str:
    keys = load_api_keys()
    if not keys:
        raise HTTPException(status_code=503, detail={"error": "auth_not_configured"})

    token = _extract_bearer_token(authorization)
    if token is None:
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
