# llm-quota-gateway

A proxy gateway that sits between your application and LLM providers (OpenAI, Anthropic). It enforces per-tenant token quotas, deduplicates semantically identical requests via a pgvector cache, and writes a full cost audit log — so you know exactly who is spending what, and identical questions never hit the API twice.

---

## The Problem

Your OpenAI invoice arrives. $400. You open the dashboard and see one aggregate number. You have no idea which feature triggered it, which tenant is responsible, or which service is looping. One of your tenants is making 500 requests per day where 95% of the prompts are semantically identical — different wording, same question, same answer. Every one of those hits the API. You cannot block the abusive tenant without taking down the whole integration. You cannot set a per-plan spending cap. You find out about runaway costs only when the invoice arrives.

---

## Market Context

LLM API costs are growing faster than teams can instrument them:

- Average enterprise monthly AI spend grew from **$63K to $85.5K** (36% YoY) between 2023 and 2024 ([Andreessen Horowitz AI Survey, 2024](https://a16z.com/))
- LLM API market grew from **$3.5B to $8.4B** between late 2024 and mid-2025 — that growth is driven by production deployments, not experiments ([Menlo Ventures State of AI 2025](https://menlovc.com/))
- **37%** of enterprises surveyed report spending more than **$250K/year** on LLM API calls, with most unable to attribute spend to specific features or tenants
- Semantic deduplication studies show that in customer-facing chat products, **60–80% of prompts cluster into fewer than 200 distinct semantic intents** — meaning most API calls are redundant
- In a Zapier 2024 internal analysis, implementing a semantic cache reduced API calls by **71%** for their AI features with no measurable change in answer quality

The quota + semantic cache architecture in this gateway directly addresses the top two cost drivers: **runaway tenant usage** (token bucket enforcement) and **redundant identical requests** (pgvector similarity cache at threshold ≥0.95).

## What This Does

- **Per-tenant quota enforcement** — token budget (daily/monthly) and request rate cap, enforced before the LLM call is made. Tenant over limit gets `429` with `Retry-After`. Hard stop.
- **Semantic cache via pgvector** — every prompt is embedded and compared against cached embeddings. Cosine similarity > 0.95 = cache hit, cached response returned immediately, no API call, no cost.
- **Full audit log** — every request writes tenant ID, prompt hash, token count, cost estimate, cache hit/miss flag, provider, and latency. Queryable after the fact.
- **Drop-in replacement for OpenAI client** — gateway exposes the same `/v1/chat/completions` surface. Change one base URL in your application, nothing else.
- **Provider failover** — if OpenAI returns `429` or `5xx`, the request is automatically rerouted to Anthropic with the same payload.

---

## Architecture

```
Client
  │
  │  POST /v1/chat/completions
  ▼
┌─────────────────────────────────────────┐
│              Gateway (FastAPI)           │
│                                          │
│  1. Quota check ──────► Redis            │
│     (over limit → 429)   (token buckets) │
│                                          │
│  2. Cache check ──────► pgvector         │
│     (similarity > 0.95)  (Postgres)      │
│     cache hit → return                   │
│                                          │
│  3. LLM call ─────────► OpenAI API       │
│     (cache miss)          ▼              │
│                        Anthropic API     │
│                        (failover)        │
│                                          │
│  4. Store embedding ──► pgvector         │
│  5. Deduct tokens ────► Redis            │
│  6. Async audit log ──► Postgres         │
└─────────────────────────────────────────┘
```

---

## Stack

- **Python 3.12 + FastAPI** — async request handling
- **PostgreSQL 16 + pgvector** — semantic cache (embedding storage + cosine similarity search)
- **Redis 7** — quota counters and rate limiting (token bucket via Lua scripts)
- **OpenAI SDK + Anthropic SDK** — provider clients
- **SQLAlchemy 2.0 + Alembic** — ORM and schema migrations

---

## Quick Start

**Prerequisites:** Docker + Docker Compose + OpenAI API key

```bash
git clone https://github.com/jotive/llm-quota-gateway
cd llm-quota-gateway
make setup        # copies .env.example → .env
# Edit .env → set OPENAI_API_KEY
make up           # starts app + PostgreSQL + Redis
```

Check quota status for a tenant:

```bash
curl http://localhost:8000/quota/tenant-acme
# {"tenant_id":"tenant-acme","used_tokens":0,"limit":100000,"remaining":100000,...}
```

Make a chat completion request (proxied to OpenAI):

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: tenant-acme" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "What is Redis?"}]
  }'
# Returns OpenAI response + X-Cache: MISS header
```

Send the same (semantically equivalent) question again:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: tenant-acme" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Can you explain what Redis is?"}]
  }'
# Returns cached response + X-Cache: HIT (no API call made)
```

Check updated quota:

```bash
curl http://localhost:8000/quota/tenant-acme
# used_tokens now reflects the first request only (cache hit skipped billing)
```

Stop:

```bash
make down
```

---

## ADR Index

- [ADR-0001](docs/adr/ADR-0001-pgvector-over-dedicated-vectordb.md) — Use pgvector over dedicated vector database (Qdrant, Weaviate, Pinecone)
- [ADR-0002](docs/adr/ADR-0002-similarity-threshold-095.md) — Set semantic cache similarity threshold at 0.95
- [ADR-0003](docs/adr/ADR-0003-token-bucket-redis-lua.md) — Implement token bucket rate limiting with atomic Lua scripts in Redis
