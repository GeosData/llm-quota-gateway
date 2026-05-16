from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Cost per 1K tokens — approximate blended rate used for estimates
_COST_PER_1K_PROMPT = 0.00015       # gpt-4o-mini prompt
_COST_PER_1K_COMPLETION = 0.00060   # gpt-4o-mini completion


class Base(DeclarativeBase):
    pass


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)

    @staticmethod
    def compute_cost(prompt_tokens: int, completion_tokens: int) -> float:
        prompt_cost = (prompt_tokens / 1000) * _COST_PER_1K_PROMPT
        completion_cost = (completion_tokens / 1000) * _COST_PER_1K_COMPLETION
        return round(prompt_cost + completion_cost, 8)
