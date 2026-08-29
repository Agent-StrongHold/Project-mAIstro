---
inventory-delta:
  tests/: +4
---

# M1 #188 closeout evidence

PR #196 already landed the durable pgvector implementation for #188: vector storage on the learning row, HNSW cosine indexing, database-enforced scope filtering, and the producer/consumer path through DurableHybridLearningStore.

This follow-up corrects ADR-082326-8194 from Proposed to Accepted with dated lifecycle history and adds four root acceptance tests so the decision's existing implementation is first-class evidence in the acceptance ladder rather than an unlinked historical PR.

The real PostgreSQL behavioral suite remains `tests/migrations/test_memory_embeddings.py`; the four added root tests pin the decision contract in the always-run evidence session.

The acceptance ledger was regenerated with `check-ac-state.py --run-tests --ratchet --bank` after those four criteria all reached `reachable`. After merging current `develop` (#585's per-branch notes replaced the single `quality/ac-state.json` ratchet file), the exact banked design-coverage floor is **24.4201% over 129 taken decisions**, folded from `quality/ac-state-notes/chatgpt-m1-188-closeout.json`, with zero contradicted, unverifiable, or newly unproven completion claims.
