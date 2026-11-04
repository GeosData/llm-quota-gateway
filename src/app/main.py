from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import asyncpg
import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from src.app.core.auth import require_api_keys
from src.app.core.cache import SemanticCache
from src.app.core.quota import load_lua_script
from src.app.db.models import Base
from src.app.db.session import engine
from src.app.routes.proxy import router as proxy_router
from src.app.routes.quota import router as quota_router

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    logger.info("gateway_starting")

    require_api_keys()

    # Redis (optional — per-tenant quota is disabled if not configured)
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        redis_client = Redis.from_url(redis_url, decode_responses=True)
        await load_lua_script(redis_client)
    else:
        redis_client = None
        logger.warning("redis_not_configured", note="quota enforcement disabled")
    app.state.redis = redis_client

    # Postgres (asyncpg pool for pgvector cache)
    # asyncpg expects postgresql:// not postgresql+asyncpg://
    db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=db_url, min_size=2, max_size=10)
    cache = SemanticCache(pool=pool)
    await cache.init_schema()
    app.state.semantic_cache = cache
    app.state.pg_pool = pool

    # SQLAlchemy tables (AuditLog)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("gateway_ready")
    yield

    # --- shutdown ---
    if redis_client is not None:
        await redis_client.aclose()
    await pool.close()
    await engine.dispose()
    logger.info("gateway_stopped")


app = FastAPI(
    title="LLM Quota Gateway",
    version="0.1.0",
    description="Per-tenant quota enforcement, semantic cache, and cost audit for OpenAI-compatible providers.",
    lifespan=lifespan,
)

app.include_router(proxy_router)
app.include_router(quota_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
