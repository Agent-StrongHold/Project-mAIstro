---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +15
---
# claude-ws-1152-core-workspace-membership-scoped-run-rea-2c70

#1152 (partial): a Workspace-membership-scoped read seam for canonical Runs.

- `packages/maistro-core/tests` +15: new `tests/runs/test_scoped_reads.py`.
  Six cases run on the in-memory and SQLite store backends: member reads
  (initiator and a non-initiating member), non-member denial matching
  missing-id denial, two blank-principal variants, cross-Run child ids and a
  Project outside the Run's Workspace. One more case checks the
  `Container.run_reader` wiring. Nothing was removed or renamed.
- `packages/hive-conductor/backend/tests` +2: `test_dag_run_scope.py` gains an
  in-scope canonical overlay case and a foreign-canonical-Run no-overlay case.
  The existing overlay cases were adapted to the new reader, not removed.
