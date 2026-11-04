from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request

from src.app.core.auth import authenticate_tenant
from src.app.core.quota import get_quota_status
from src.app.schemas.openai import QuotaStatusResponse

router = APIRouter()

_DEFAULT_QUOTA_LIMIT = int(os.environ.get("DEFAULT_QUOTA_LIMIT", 100_000))


@router.get("/quota/{tenant_id}", response_model=QuotaStatusResponse)
async def quota_status(
    tenant_id: str,
    request: Request,
    authenticated_tenant: str = Depends(authenticate_tenant),
) -> QuotaStatusResponse:
    if tenant_id != authenticated_tenant:
        raise HTTPException(status_code=403, detail={"error": "tenant_mismatch"})

    redis_client = request.app.state.redis
    if redis_client is None:
        raise HTTPException(status_code=503, detail={"error": "quota_not_configured"})

    used, remaining, resets_in = await get_quota_status(
        redis_client=redis_client,
        tenant_id=tenant_id,
        limit=_DEFAULT_QUOTA_LIMIT,
    )
    return QuotaStatusResponse(
        tenant_id=tenant_id,
        used_tokens=used,
        limit=_DEFAULT_QUOTA_LIMIT,
        remaining=remaining,
        window_resets_in=resets_in,
    )
