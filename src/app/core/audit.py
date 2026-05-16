from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.db.models import AuditLog

logger = structlog.get_logger(__name__)


async def write_audit(
    session: AsyncSession,
    tenant_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    cached: bool,
) -> None:
    cost = AuditLog.compute_cost(prompt_tokens, completion_tokens)

    entry = AuditLog(
        tenant_id=tenant_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached=cached,
        estimated_cost_usd=cost,
    )
    session.add(entry)
    await session.commit()

    logger.info(
        "audit_written",
        tenant_id=tenant_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached=cached,
        estimated_cost_usd=cost,
    )
