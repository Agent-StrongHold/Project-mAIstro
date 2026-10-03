---
inventory-delta:
  packages/maistro-core/tests: +3
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 25: coverage and startup-double repair

Adds a `runs/test_wiring.py` regression that drives both outcomes of
`wire_node_template_store`'s canonical-spine probe: a migrated caller-owned
PostgreSQL pool selects `PgNodeTemplateStore`; without a durable spine it uses
`InMemoryNodeTemplateStore`.

Also updates the engine-startup atomicity test double to accept the
`idempotency_store` keyword that `LocalTaskBackend` now passes to every
`TaskQueue`. The test therefore again reaches the intended runner-startup
failure and verifies recovery cadences are unwound, instead of failing at the
mock constructor.

Adds coverage-gate regressions for the two production branches the CI evidence
had not reached: `PgRunStore.find_run_by_task_receipt` is driven through a
recording asyncpg-shaped pool and verifies its JSONB task-receipt predicate;
the public `spine_is_migrated` probe is driven through its missing-table path.
The first protects ambiguous task-admission recovery's PostgreSQL discovery
seam, and the second protects claims following the canonical Run tier rather
than outliving it.
