---
inventory-delta:
  formal/: +3
---
# Issue 881 — execution-lifecycle state machine (research prototype M8-A1)

Three node IDs under `formal/models/test_execution_lifecycle_state.py`:

- `...::TestExecutionLifecycleMachine` — a Hypothesis `RuleBasedStateMachine`
  (collects as one test) driving the real `PgRunStore` across all three spine
  levels; five rules generate moves for Run, NodeRun and Attempt from the full
  status sets, and six invariants compare the store against independently
  evolved table arithmetic.
- `...::test_completion_of_the_run_is_earned_by_its_latest_node_run` —
  deterministic witness for the #241 earned-completion contract, both
  directions, including the retry-via-new-NodeRun path.
- `...::test_attempt_completion_is_refused_under_a_terminal_run` —
  deterministic witness for the #1335 fence and the closed-Run-refuses-work
  guards.

`pytest formal/models --collect-only -q` collects 664 nodes before and 667
after (baseline `docs/testing/inventory/baseline.json` formal/ = 417 plus open
deltas). Like I29, the machine is about the PostgreSQL store, so it skips
without `MAISTRO_TEST_PG_DSN`; `formal-conformance.yml` already provisions the
service, so nothing skips in CI. Runs at the PR budget in ~4-8s; measured
60-example run 17.6s, so nightly budgets for this module should stay on the
`MAISTRO_FORMAL_PG_EXAMPLES` knob rather than the default 10k.

The six-mutant demonstration battery and the research disposition live in
`docs/research/881-execution-lifecycle-state-machines.md`.
