# ADR-0002: Set semantic cache similarity threshold at 0.95

**Status:** Accepted

---

## Context

The semantic cache returns a cached response when a new prompt's embedding is sufficiently similar to a stored embedding. The threshold controls where "sufficiently similar" begins.

The risk runs in both directions:

- **Threshold too low** — semantically different questions get treated as equivalent. The cache returns a wrong answer. This is the worse failure mode: silent, incorrect responses served to users.
- **Threshold too high** — only near-exact duplicate prompts match. Cache hit rate approaches zero. The cache provides no cost or latency benefit.

The threshold needs to be validated against real prompt distributions, not set by intuition.

---

## Decision

Set cosine similarity threshold at **0.95**.

Validation was done on a sample of 500 real queries drawn from production-like traffic (varied phrasing of the same underlying questions, plus genuinely distinct questions as negative examples):

| Threshold | False positives (different questions matched) | Estimated hit rate |
|---|---|---|
| 0.90 | 12 | ~38% |
| 0.92 | 4 | ~31% |
| 0.95 | 0 | ~24% |
| 0.97 | 0 | ~11% |

At 0.95, zero false positives were observed. Questions with different intent that were phrased similarly did not cross the threshold. At 0.90, 12 cases of semantically distinct questions were matched — unacceptable for a production cache.

---

## Consequences

**Positive:**
- Zero false answers served from cache in validation set.
- 24% hit rate still represents meaningful cost reduction on repetitive workloads.
- Conservative threshold means the cache degrades gracefully: a miss costs nothing beyond the embedding lookup.

**Negative:**
- Hit rate is lower than theoretically achievable. At 0.92, hit rate was ~31% with only 4 false positives — a tighter call, but still unacceptable for correctness guarantees.
- The threshold is fixed at deploy time. Workloads with higher paraphrase diversity may benefit from per-tenant threshold configuration in a future iteration.

**Accepted trade-off:** Correctness over cache efficiency. A wrong answer from cache is worse than an extra API call.
