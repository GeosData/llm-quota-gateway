from __future__ import annotations

import json
import os

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.audit import write_audit
from src.app.core.cache import SemanticCache
from src.app.core.quota import check_and_consume
from src.app.db.session import get_session
from src.app.schemas.openai import ChatCompletionRequest, ChatCompletionResponse

logger = structlog.get_logger(__name__)

router = APIRouter()

_UPSTREAM_CHAT_URL = os.environ.get("LLM_CHAT_URL", "https://api.openai.com/v1/chat/completions")
_DEFAULT_QUOTA_LIMIT = int(os.environ.get("DEFAULT_QUOTA_LIMIT", 100_000))
_QUOTA_WINDOW_SECONDS = int(os.environ.get("QUOTA_WINDOW_SECONDS", 3600))


def _prompt_text(request: ChatCompletionRequest) -> str:
    parts: list[str] = []
    for msg in request.messages:
        content = msg.content
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    app_state = request.app.state
    redis_client = app_state.redis
    cache: SemanticCache = app_state.semantic_cache

    prompt = _prompt_text(body)

    # 1. Semantic cache check
    cached_response = await cache.get(prompt)
    if cached_response is not None:
        cached_data = json.loads(cached_response)
        usage = cached_data.get("usage", {})
        await write_audit(
            session=session,
            tenant_id=x_tenant_id,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=cached_data.get("model", body.model),
            cached=True,
        )
        return Response(
            content=cached_response,
            media_type="application/json",
            headers={"X-Cache": "HIT"},
        )

    # 2. Quota check — estimate token cost before calling the provider
    # (skipped when Redis is not configured)
    if redis_client is not None:
        estimated_tokens = max(len(prompt) // 4, 1) + (body.max_tokens or 200)
        allowed, remaining, retry_after = await check_and_consume(
            redis_client=redis_client,
            tenant_id=x_tenant_id,
            tokens_requested=estimated_tokens,
            limit=_DEFAULT_QUOTA_LIMIT,
            window_seconds=_QUOTA_WINDOW_SECONDS,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"error": "quota_exceeded", "tenant_id": x_tenant_id, "remaining": remaining},
                headers={"Retry-After": str(retry_after)},
            )

    # 3. Forward to the upstream provider (any OpenAI-compatible endpoint)
    upstream_key = os.environ.get("LLM_API_KEY") or os.environ["OPENAI_API_KEY"]
    payload = body.model_dump(exclude_none=True)

    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.post(
            _UPSTREAM_CHAT_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {upstream_key}",
                "Content-Type": "application/json",
            },
        )

    if upstream.status_code != 200:
        logger.error(
            "upstream_error",
            status_code=upstream.status_code,
            body=upstream.text[:500],
        )
        raise HTTPException(
            status_code=upstream.status_code,
            detail=upstream.json() if upstream.headers.get("content-type", "").startswith("application/json") else upstream.text,
        )

    response_data = upstream.json()
    usage = response_data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)

    # 4. Write audit log
    await write_audit(
        session=session,
        tenant_id=x_tenant_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=response_data.get("model", body.model),
        cached=False,
    )

    # 5. Store in semantic cache (fire-and-forget style — errors are logged, not raised)
    response_json_str = json.dumps(response_data)
    try:
        await cache.set(prompt, response_json_str)
    except Exception as exc:
        logger.warning("cache_store_failed", error=str(exc))

    # 6. Return response
    return Response(
        content=response_json_str,
        media_type="application/json",
        headers={"X-Cache": "MISS"},
    )
