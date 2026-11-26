---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +25
---
# claude-ws-1152-core-workspace-membership-scoped-run-rea-2c70

#1152 (partial): a Workspace-membership-scoped read seam for canonical Runs.

- `packages/maistro-core/tests` +25: new `tests/runs/test_scoped_reads.py`.
  Cases run on the in-memory and SQLite store backends: member reads
  (initiator and a non-initiating member), non-member denial matching
  missing-id denial, two blank-principal variants, cross-Run child ids, a
  missing Project, a Project filed in another Workspace, a membership revoked
  mid-read, the batched `get_runs`, an unreadable stored Run (archived with
  no archive tier) denied like a missing one, and a batch that skips one
  unreadable Run but keeps the rest. One more case checks the
  `Container.run_reader` wiring. Nothing was removed or renamed.
- `packages/hive-conductor/backend/tests` +4: `test_dag_run_scope.py` gains an
  in-scope canonical overlay case, a foreign-canonical-Run no-overlay case and
  a no-overlay case for a Run filed in a different Workspace than its row,
  and `test_dag_run_cancel_route.py` gains a list-path overlay case. The
  existing overlay cases were adapted to the new reader, not removed.
