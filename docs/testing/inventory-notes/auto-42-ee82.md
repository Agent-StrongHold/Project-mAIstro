---
inventory-delta:
  packages/maistro-core/tests: -38
  packages/maistro-server/tests: -1
  tests/: +4
---
# auto-42-ee82

Develop sync of `origin/develop` (df00785bb41b6, M1-B1 canonical Run routing +
06a65a8ea, M9-C1 extension contract versioning) into `auto-42`, resolving the
preserved conflict round. Net recorded delta per suite above; gross moves:

- `packages/maistro-core/tests` **+121 added** by the sync (all additions, none
  removed, verified per-file against a fully-synced pre-merge worktree at
  188242751): `tests/extensions/test_compat.py` +67 and
  `tests/extensions/test_cli_compat.py` +6 (new from 06a65a8ea),
  `tests/runs/test_spine_conformance.py` +4 and `tests/runs/test_wiring.py` +2,
  `tests/tasks/test_idempotency.py` +28, `tests/tasks/test_idempotency_durable.py`
  +10 (df00785bb), `tests/tasks/test_replay_receipt_durable_row.py` +4 (new).
- `packages/maistro-server/tests` **+6 added** (`tests/api/test_tasks_idempotency.py`).
- `tests/` **+16 added** (`tests/migrations/test_migration_conftest_restore.py` +6
  new, `test_migration_chain.py` +4, `tests/test_gates_ran_publisher_contract.py` +6).

The recorded net is smaller than the additions because the ledger was already
stale at the prior head **188242751**: collecting there (fully-synced venv,
same recipe as this gate) yields core 14538 vs expected 14697 (−159), server
534 vs 541 (−7), root 4731 vs 4743 (−12) — **−178 pre-existing**. Attribution:
develop's landed #41 work heavily rewrote `tests/tasks/test_idempotency*.py`
and `tests/api/test_tasks_idempotency.py` after earlier notes had recorded
deltas for their pre-rewrite shapes; those stale deltas only reach this branch
through develop syncs, and no prior round collected a full local reconciliation
against them. This note true-ups the combined gap for the branch; `--compact`
will fold it at the next compaction.

Post-merge collection: 28052 node IDs, 0 cross-suite duplicates, 0
byte-identical test files.
