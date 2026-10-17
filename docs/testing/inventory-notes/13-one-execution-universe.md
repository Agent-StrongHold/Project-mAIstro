---
inventory-delta:
  # No net test delta on this branch: the 2026-09-11 closeout attempt's three
  # added tests were superseded by develop's canonical implementations of the
  # same acceptance (#1194 replay contract, #1193 composition failure, #1199
  # canonical tick) and were dropped during the develop merge reconciliation.
  # Develop's own notes carry those suites' deltas.
---

# Issue 13 — one execution universe (develop reconciliation)

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
  (`test_scheduler_canonical_admission.py`).

The merge into develop (ab8b3737) therefore takes develop's side for every
overlapping hunk and removes the branch-local test variants
(`_UnsafeFlakyStep`, `test_tick_reads_due_schedules_from_canonical_store`);
they duplicated develop's canonical coverage and no longer compiled against
the `ReplaySemantics` contract. This note records that reconciliation so the
ledger does not count tests this branch no longer adds.
