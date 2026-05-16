from __future__ import annotations

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

# Lua script: atomic check-and-consume for token bucket.
# KEYS[1] = redis key for tenant counter
# ARGV[1] = tokens_requested
# ARGV[2] = limit
# ARGV[3] = window_seconds
#
# Returns {allowed (0|1), remaining}
_LUA_SCRIPT = """
local key = KEYS[1]
local requested = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local window = tonumber(ARGV[3])

local current = tonumber(redis.call('GET', key) or 0)

if current + requested > limit then
    local ttl = redis.call('TTL', key)
    if ttl < 0 then ttl = window end
    return {0, limit - current, ttl}
end

local new_val = redis.call('INCRBY', key, requested)
local ttl = redis.call('TTL', key)
if ttl == -1 then
    redis.call('EXPIRE', key, window)
    ttl = window
end

return {1, limit - new_val, ttl}
"""

_script_sha: str | None = None


async def load_lua_script(redis_client: Redis) -> None:
    global _script_sha
    _script_sha = await redis_client.script_load(_LUA_SCRIPT)
    logger.info("quota_lua_loaded", sha=_script_sha)


async def check_and_consume(
    redis_client: Redis,
    tenant_id: str,
    tokens_requested: int,
    limit: int,
    window_seconds: int = 3600,
) -> tuple[bool, int, int]:
    """Check quota and consume tokens atomically.

    Returns:
        (allowed, remaining, ttl_seconds)
    """
    if _script_sha is None:
        raise RuntimeError("Lua script not loaded. Call load_lua_script() at startup.")

    key = f"quota:{tenant_id}"
    result = await redis_client.evalsha(
        _script_sha,
        1,
        key,
        tokens_requested,
        limit,
        window_seconds,
    )
    allowed = bool(result[0])
    remaining = int(result[1])
    ttl = int(result[2])

    logger.debug(
        "quota_check",
        tenant_id=tenant_id,
        tokens_requested=tokens_requested,
        allowed=allowed,
        remaining=remaining,
        ttl=ttl,
    )
    return allowed, remaining, ttl


async def get_quota_status(
    redis_client: Redis,
    tenant_id: str,
    limit: int,
) -> tuple[int, int, int]:
    """Return (used_tokens, remaining, ttl_seconds) without consuming."""
    key = f"quota:{tenant_id}"
    pipe = redis_client.pipeline()
    pipe.get(key)
    pipe.ttl(key)
    current_raw, ttl = await pipe.execute()

    used = int(current_raw or 0)
    remaining = max(0, limit - used)
    resets_in = max(0, int(ttl)) if ttl and ttl > 0 else 0
    return used, remaining, resets_in
