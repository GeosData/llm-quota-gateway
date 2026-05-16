from __future__ import annotations

import os

from fastapi import APIRouter, Request

from src.app.core.quota import get_quota_status
from src.app.schemas.openai import QuotaStatusResponse

router = APIRouter()

_DEFAULT_QUOTA_LIMIT = int(os.environ.get("DEFAULT_QUOTA_LIMIT", 100_000))


@router.get("/quota/{tenant_id}", response_model=QuotaStatusResponse)
async def quota_status(tenant_id: str, request: Request) -> QuotaStatusResponse:
    redis_client = request.app.state.redis
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
