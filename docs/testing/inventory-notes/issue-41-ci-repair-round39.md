---
inventory-delta:
  tests/: +0
---

# Issue #41 CI-repair round 39: PostgreSQL coverage migration reconciliation

The reported coverage failure was reproduced in the exact PostgreSQL producer
shape against a live PostgreSQL 17 service. `tests/migrations` failed because
#1845's reconciled revision 038 already makes `claim_token` and `completed_at`
part of the shipped `task_idempotency` schema, while the newly merged forward
admission-generation tests still treated both as optional, post-038 additions.
That made their fixture inserts violate the real `NOT NULL` constraint and
made the runtime-provisioning chain test assert the pre-054 column set after
upgrading to head.

The existing tests now model the reachable schema: legacy rows include the
038-owned token and completion fields; the forward test preserves that real
shape; the full-chain assertion includes revision 054's generation columns;
and the null-refusal assertion recognizes that 038's physical `NOT NULL`
constraint is the stronger rejection for `claim_token`. No test identities
were added or removed.

Live validation:
`MAISTRO_TEST_DATABASE_URL=postgresql://maistro:maistro@127.0.0.1:55432/maistro_test uv run pytest tests/migrations/test_task_admission_generation_upgrade.py tests/migrations/test_migration_chain.py::TestTheChainSurvivesRuntimeSelfProvisioning -q -x`
passed: **18 passed**. The migration-session finish hook restored the shared
service to Alembic head for the remaining coverage producer suites.
