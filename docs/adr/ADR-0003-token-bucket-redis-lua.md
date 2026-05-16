# ADR-0003: Implement token bucket rate limiting with atomic Lua scripts in Redis

**Status:** Accepted

---

## Context

Per-tenant quota enforcement must be exact under concurrent requests. A tenant sending 50 parallel requests must not be able to exceed their token budget due to a race condition between read and write.

Options evaluated:

| Option | Atomicity | Notes |
|---|---|---|
| Application-level counters (in-memory) | No | Not shared across gateway replicas. Race conditions under concurrency. |
| Redis `INCR` / `DECRBY` | Partial | Atomic increment is fine, but bucket refill logic (restore tokens on time window expiry) requires multiple commands — not atomic as a unit. |
| Redis Lua script (`EVALSHA`) | Yes | Entire check + decrement + conditional refill executes as a single atomic operation in Redis. |
| Redis `MULTI`/`EXEC` (transaction) | Optimistic | Requires watch + retry loop. More complex, not O(1) under contention. |

The token bucket algorithm is the right model: each tenant has a bucket with a maximum token capacity. Tokens are consumed by each request (proportional to the request's token count). The bucket refills at a fixed rate (e.g., 10,000 tokens per minute). This handles burst traffic fairly while enforcing sustained rate limits.

---

## Decision

Implement the token bucket algorithm as a Redis Lua script executed via `EVALSHA`.

The Lua script performs the full bucket logic in a single atomic call:
1. Read current token count and last refill timestamp.
2. Calculate tokens to add based on elapsed time since last refill.
3. Cap at bucket maximum.
4. Check if request token cost can be satisfied.
5. If yes: deduct tokens, update timestamp, return allow.
6. If no: return deny with time-until-refill.

One `EVALSHA` call per request. No race condition window.

---

## Consequences

**Positive:**
- Quota enforcement is exact with no over-counting under any level of concurrency.
- Single round-trip to Redis per request — no retry loops, no optimistic locking overhead.
- Bucket state (current tokens + timestamp) is stored in two Redis keys per tenant. Minimal memory footprint.

**Negative:**
- Lua script logic must be tested independently — bugs in the script are hard to observe from the application layer.
- Script must be loaded into Redis on startup (`SCRIPT LOAD`) and the SHA cached. If Redis restarts and the script is evicted, the application must reload it. This is handled in the startup sequence but adds a startup dependency.
- Lua scripts block other Redis commands for their duration. Script must be kept minimal — no I/O, no loops over unbounded data.

**Accepted trade-off:** The correctness guarantee (no race conditions, exact quota enforcement) justifies the operational care required for the Lua script. The script is short, deterministic, and unit-testable in isolation.
