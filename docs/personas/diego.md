# Persona: Diego

**Role:** CTO, AI-powered legal document assistant startup
**Company:** SaaS — 200 paying customers, OpenAI-backed
**Team:** 4 engineers

## The Pain

Two concrete problems:

**1. No per-tenant quota.** All 200 customers share the same OpenAI API key. A free-trial customer can burn the same tokens as an enterprise customer. Last month a misconfigured job looped and generated $800 in LLM calls in 4 hours — no one noticed until the bill arrived.

**2. No caching.** "What is the penalty clause in this contract?" is asked 40 times a day by different users. Each request hits OpenAI. Same document, same question, same answer — 40 API calls, 40× latency, 40× cost. The answer doesn't change between requests.

**Consequence:** Unpredictable monthly OpenAI bill. No cost ceiling per customer plan. No visibility into which customers are consuming what. No way to offer a free tier safely.

## What Diego Needs

- Hard quota per customer per billing period — free tier physically cannot exceed the limit
- Semantic cache that serves repeated questions from memory, not from OpenAI
- Full audit log: every prompt, every response, every token count
- Provider failover so an OpenAI outage doesn't take down the product

## What Success Looks Like

Monthly LLM bill predictable within ±10%. Free-tier customers self-contained. Cache hit rate >30% within first week of deployment.
