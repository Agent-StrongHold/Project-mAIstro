---
inventory-delta:
  packages/maistro-core/tests: +61
  packages/maistro-server/tests: +6
  tests/: -2
---
# auto-41-5cc9

Issue #41 (M1-B1, canonical Run routing) plus its child #1176 (task-admission
idempotency) rewrote four test files; every delta below is collected node IDs
(parametrization included) against the last recorded baseline.

- `packages/maistro-core/tests` +61 — `tests/tasks/test_idempotency.py`
  (36 -> 52 test functions: payload-fingerprint replay, the ambiguous window,
  claimant takeover and the claim-token fence) and
  `tests/tasks/test_idempotency_durable.py` (18 -> 27: the SQLite file-reopen
  durability box and the live-PostgreSQL reconciliation test).
- `packages/maistro-server/tests` +6 — `tests/api/test_tasks_idempotency.py`
  (7 -> 13: HTTP-level replay of the same `run_id`, 409 on fingerprint
  mismatch, per-principal scoping).
- `tests/` -2 — `tests/migrations/test_migration_chain.py` (11 -> 15 test
  functions): the runtime-self-provisioning adoption/refusal cases for the
  `task_idempotency` chain migration replaced the earlier live-PG cases, whose
  collected IDs differed; the reconciled file nets two fewer collected IDs
  against the baseline while asserting strictly more (column types,
  nullability, default, primary key, expiry index).
