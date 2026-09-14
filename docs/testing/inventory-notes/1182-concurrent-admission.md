---
inventory-delta:
  packages/maistro-core/tests: +4
---

The concurrency admission tests cover per-principal fairness, deterministic release on terminal Run and Attempt transitions, and stale lease reclamation. The production wiring and PostgreSQL migration are also exercised by the existing Run wiring suite; the PostgreSQL implementation uses the shared lease table and advisory locks rather than process-local semaphores.
