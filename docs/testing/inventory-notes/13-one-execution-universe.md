---
---

# Issue 13 — one execution universe (develop reconciliation, revalidated 2026-10-20)

The 2026-09-11 closeout commit (c4fa327b) implemented the epic's three
Core-review requirements (#1194 node retry/idempotency, #1193 synth-DAG
mandatory dependencies, #1199 canonical scheduler tick) ahead of develop.
Develop has since landed canonical implementations of the same acceptance that
supersede that branch-local variant:

- #1194 — `ReplaySemantics`/`logical_effect_key` executable replay contract in
  `maistro/graph/durable_runs/{executor,attempt_executor}.py` with
  `test_attempt_executor.py` regression coverage
  (`test_non_retryable_contract_overrides_a_graph_retry_budget`,
  `test_resume_never_reexecutes_a_non_retryable_nodes_ambiguous_effect`).
- #1193 — `agent.synth_dag` without the canonical run store now raises
  `NodeCompositionError` (missing `graph_run_store`/`run_store`) instead of
  returning a success-shaped no-op, plus canonical child admission
  (`_admit_child`) before the first checkpoint.
- #1199 — the configured tick enumerates candidates from
  `ScheduleStore.due()` (`_tick_due`), re-reads canonical truth under
  `definition_lock`, persists cursors through the canonical store, and the
  bounded consumer executes admitted Runs
  (`packages/hive-conductor/backend/tests/test_scheduler_canonical_admission.py`).

The merge into develop (ab8b3737) therefore takes develop's side for every
overlapping hunk and removes the branch-local test variants
(`_UnsafeFlakyStep`, `test_tick_reads_due_schedules_from_canonical_store`);
they duplicated develop's canonical coverage and no longer compiled against
the `ReplaySemantics` contract. This note records that reconciliation so the
ledger does not count tests this branch no longer adds.

## Revalidation on the fad17a87c sync (2026-10-20)

The branch was re-synced to `origin/develop` at fad17a87c (merge 552658ace;
clean, no conflicts — the only branch-local file is this note). The three
requirements were rechecked against reachable production behavior rather than
assuming the earlier note's claims:

- #1194 — `ReplaySemantics` present in `executor.py` (contract field,
  `_may_revisit_after` gate) and `attempt_executor.py` (`_node_replay_semantics`,
  `_replay_refused`); the two regression tests pass.
- #1193 — `NodeCompositionError` raised at `agent_synth_dag.py` composition
  when the durable run store is absent; `test_agent_synth_dag.py` asserts
  `error_code == "NodeCompositionError"` (32 tests pass).
- #1199 — `scheduler.py` canonical tick wired (`_tick_due`,
  `definition_lock`, `schedule_store` cursors);
  `test_scheduler_canonical_admission.py` passes (16 tests).

Focused suites on the synced tree: `graph/durable_runs` 710 passed,
`graph/nodes` 601 passed, conductor scheduling 185 passed, `runs` 1320
passed, `scheduling` 274 passed; `ruff check` and `ruff format --check` clean.

No test count moves on this change, so no `inventory-delta` is recorded. The
epic's remaining open items are owned elsewhere: direct children #41, #42,
#44, #46, #47, #48, open nested items #251 and #1082, sub-issue #1612
(GraphExecutionState load/fork at event sequence N), and #1192 (hierarchy-
owned by M1-E #62). This note intentionally does not close them.
