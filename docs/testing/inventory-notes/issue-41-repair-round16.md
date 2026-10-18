---
inventory-delta:
  tests/: +0
---

# Issue 41 repair (round 16): focused revalidation of head 577fab0f5

No test delta: this round changed no code. The worktree arrived clean at
`577fab0f585373c20108941bece3534352074a99` (the round-15 head) and the prior
run's only recorded failure was a missing result record, not a code defect.
This note records the re-executed validation battery that proves the head.

## Battery executed (all green)

| Check | Outcome |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 2584 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0; ratchet holds, 1403 reviewed identities → 1403 findings |
| `uv run python scripts/check-suite-inventory.py` | ok: 14 suites match the recorded inventory |
| `uv run python scripts/check-ac-state.py` | exit 0 (writes gitignored `quality/ac-state.json`) |
| `uv run pytest packages/maistro-core/tests/tasks/test_idempotency.py packages/maistro-core/tests/tasks/test_idempotency_durable.py packages/maistro-core/tests/tasks/test_idempotency_purge_driven.py -q` | 105 passed, 8 skipped |
| `uv run pytest packages/maistro-core/tests/runs/test_parked_run_resume.py packages/maistro-core/tests/runs/test_spine_conformance.py -q` | 289 passed, 118 skipped |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_idempotency.py packages/hive-conductor/backend/tests/test_engine_service.py tests/migrations/test_migration_chain.py tests/test_gates_ran_publisher_contract.py -q` | 60 passed, 15 skipped |

`scripts/check-gates-ran.py` and `scripts/check-integration-scope.py` are
CI-event-parameterized (required `--check-runs` / `--event-name` args) and are
covered locally by `tests/test_gates_ran_publisher_contract.py`, which passes —
including the round-15 cancelled-publisher regression for GitHub run
36274594751.

## Acceptance seams re-verified against production code

- Task admission yields a canonical run id with idempotency provenance:
  `packages/maistro-core/src/maistro/tasks/admission.py` (`TaskRunAdmitter.admit`
  returns `run.run_id`, records `IDEMPOTENCY_KEY_PROVENANCE`).
- Durable scoped idempotency contract (#1176): `tasks/idempotency.py` —
  `request_fingerprint`, `admission_scope_key`, `Claimed/Replayed/Pending/Ambiguous`
  outcomes, Pg + Sqlite stores, `resolve_run`, purge/expiry/take-over semantics;
  durable table shipped by `alembic/versions/038_task_idempotency.py`.
- One-node Graph for direct/chat work: `runs/chat_admission.py` ("Admit one chat
  turn as a Run over the trivial one-node Graph"), consumed by
  `runs/chat_execution.py` / `runs/consumption.py` (single-node allowlisted sources).
- Server wiring: `packages/maistro-server/src/maistro_server/main.py` wires
  `idempotency_store=container.task_idempotency` and documents the one-node
  Run + run_id response contract for `/tasks` and chat.

## Residual, not resolvable from this worktree

The previous block ("GH006: Protected branch update failed for
refs/heads/auto-41 … queued for merging") is a push/dequeue action against
GitHub. Branch pushes are prohibited for this worker, so the local head
`577fab0f5` is committed here and the push/dequeue remains an
integration-phase step for the driver.
