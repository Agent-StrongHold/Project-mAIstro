---
inventory-delta:
  tests/: +0
---

# Issue #41 verification round (job 84e3aa12e82a4c5e9b9432b07c11ccf6)

No test delta: this is an evidence-only verification note for the repair-phase
re-validation of issue #41 at head `e9b9080ec8ef457d24058008819f87ae8d3827ac`.
The prior round's failure was a missing result record, not a code defect; every
acceptance criterion was re-proven here against reachable production behavior
instead of being assumed from earlier notes.

## Acceptance battery (all executed at the assigned head)

- `uv run pytest packages/maistro-core/tests/tasks/ -q` — 407 passed,
  15 skipped (PG-gated legs).
- `uv run pytest` over `packages/maistro-core/tests/runs/test_admission.py
  test_chat_admission.py test_chat_execution.py test_chat_attempt_recovery.py
  test_chat_retention_sweep.py test_task_kinds.py test_spine_conformance.py
  test_parked_run_resume.py test_wiring.py` — 445 passed, 124 skipped
  (PG-gated).
- Same runs PG-backed via `MAISTRO_TEST_PG_DSN` against pgvector pg17
  (`test_spine_conformance.py`, `test_idempotency_durable.py`,
  `test_idempotency_purge_driven.py`) — 416 passed, 0 skipped: the durable
  replica-shareable idempotency tier (#1176) is exercised for real, not only
  in memory/sqlite.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_idempotency.py
  test_tasks_run_identity.py test_chat_completions.py
  test_chat_completions_gate.py test_tasks.py -q` — 96 passed: run_id is
  returned by `/v1/tasks` (`TaskCreatedResponse.run_id`) and by
  `/v1/chat/completions` (`X-Maistro-Run-Id` header and response body).
- `uv run pytest packages/hive-conductor/backend/tests/ -q` — 2,937 passed,
  6 skipped: Conductor-side submission parity.
- `uv run pytest tests/test_gates_ran_publisher_contract.py -q` — 12 passed.
- `uv run ruff check .` / `uv run ruff format --check .` — clean
  (2,605 files formatted).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — exit 0: 1,402 reviewed
  identities equal 1,402 findings, `unclassified: 0`, `never_allowlist: 0`.
  No ledger amendment warranted (nothing fixed, nothing eliminated).

## Migration chain evidence and the shared-database caveat

`tests/migrations/test_migration_chain.py` failed 8/16 when pointed at the
long-lived shared `maistro_test` database. Manual reproduction on a scratch
database in the same server — `alembic upgrade head` then
`alembic downgrade base` — round-trips cleanly with the branch's chain
(including `038_task_idempotency` and develop's `036_audit_log_org_scope`
autocommit-block concurrent-index downgrade). Re-running the suite against a
fresh scratch database passes 16/16. The failures are state pollution in the
shared database (tables created outside the chain by wire-time `ensure_schema`
and earlier coverage runs), not a chain defect; the suite's own fixture starts
from `downgrade base` and cannot survive extra foreign tables. Wire these
tests at a per-run database, as CI does.

## Previous block resolution

The prior round's terminal error was a launch/preflight `git push` rejection
(GH006: `auto-41` is protected and its PR sits in a merge queue). That is a
push-path failure, not a develop sync conflict: locally the branch contains the
assigned base `b43175c1d` (merge-base) and the working tree at the assigned
head is clean. No conflict resolution is owed; pushing remains prohibited for
this worker.

## Residuals

- #131 (chat-run retention/granularity decision) is open upstream; retention
  machinery itself is covered here (`test_retention_*.py`,
  `test_chat_retention_sweep.py` pass), and only #1176 gates #41's acceptance.
- The shared `maistro_test` database on this host carries out-of-chain tables;
  PG-gated suites that assert on the raw catalog must use fresh databases.
