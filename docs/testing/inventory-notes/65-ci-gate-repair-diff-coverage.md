---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/hive-conductor/backend/tests: +1
---
# Issue #65 CI-gate repair — diff-coverage floor on the Goal inspection seams

CI-repair round for #65 (`auto-65`). The merge-queue evaluation failed the
`Coverage gate (publish-set floor + diff coverage)` on two changed files whose
new lines nothing executed:

- `packages/hive-conductor/backend/services/engine.py` — the `goal_reader`
  seam property: the existing Goal inspection tests bridge the engine with a
  `SimpleNamespace`, so the property body (the container getattrs) never ran.
- `packages/maistro-core/src/maistro/runs/scoped_reads.py` —
  `list_recent_runs`' per-row Workspace re-check (`run.workspace_id ==
  workspace_id and await self._admits(...)`) had only its true outcome
  exercised: every shipped store pre-filters discovery by Workspace, so no
  real store ever hands the reader an out-of-scope row.

Two tests, one per seam:

- `test_engine_goal_reader_degrades_without_a_container_bridge` in
  `packages/hive-conductor/backend/tests/test_goal_inspection.py` mirrors the
  `graph_run_store` degradation test: the seam is None without an agent port,
  None with a container that carries no Goal reader, and exactly the
  container's object (no wrapper) when present — the fail-closed shape Goal
  inspection depends on.
- `test_recent_discovery_refilters_rows_answered_out_of_scope` in
  `packages/maistro-core/tests/runs/test_scoped_reads.py` wraps the store
  with one that answers discovery out of scope, and makes the principal a
  member of both Workspaces so Project admission alone cannot explain the
  outcome: the foreign-Workspace row must be dropped by the reader's own row
  re-check, and only the member's own history survives. Shown to fail when
  the Workspace equality is removed from the condition. The scoped-reads test
runs on both store backends (the suite's memory/sqlite parametrization), so
maistro-core collects two node IDs for it.

One test added to the conductor suite (+1) and one parametrized-over-backends
test added to maistro-core (+2); none removed; no other suite moved. The
`test` job's npm-audit failure (vite 8.1.5 launch-editor advisories) is
fixed by the lockfile-only bump to vite 8.1.6 and moves no suite.
