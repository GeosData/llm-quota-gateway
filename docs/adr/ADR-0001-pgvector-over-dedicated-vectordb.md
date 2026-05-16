# ADR-0001: Use pgvector over dedicated vector database (Qdrant, Weaviate, Pinecone)

**Status:** Accepted

---

## Context

The semantic cache requires vector similarity search: store prompt embeddings, query by cosine similarity at request time, return cached responses above a threshold.

Options evaluated:

| Option | Type | Operational footprint |
|---|---|---|
| pgvector | Postgres extension | Existing Postgres instance |
| Qdrant | Dedicated vector DB | Additional service to run and operate |
| Weaviate | Dedicated vector DB | Additional service, heavier resource profile |
| Pinecone | Managed SaaS | External dependency, per-vector pricing |

All tenant data, audit logs, quota configurations, and cache entries need to be consistent with each other. Tenants are in Postgres. Audit logs go to Postgres. Quota configs are in Postgres. The cache is conceptually part of the same data layer.

---

## Decision

Use pgvector as the vector store for semantic cache embeddings.

Single database to operate. ACID transactions span cache lookups, audit log writes, and tenant data — no cross-service consistency problem. IVFFlat index on the embedding column is sufficient for cache sizes under 1M vectors, which covers the realistic scale of this use case. Backup, monitoring, and connection pooling are already solved for Postgres.

---

## Consequences

**Positive:**
- No additional infrastructure component to provision, monitor, or back up.
- Cache hits and audit log writes can be wrapped in a single transaction if needed.
- Operational complexity stays flat as the system grows to its expected scale.

**Negative:**
- pgvector is not optimal for billion-scale vector workloads. ANN (Approximate Nearest Neighbor) performance degrades beyond ~10M vectors without careful index tuning.
- At very high query throughput, a dedicated vector DB (Qdrant) would offer better query isolation from OLTP traffic.

**Accepted trade-off:** The cache size ceiling is well within pgvector's reliable operating range. If the system outgrows it, migration to a dedicated store is a contained change (swap the similarity search layer, keep everything else).
