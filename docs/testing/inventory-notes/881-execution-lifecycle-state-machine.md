---
inventory-delta:
  formal/: +3
  tests/: +1
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

`pytest formal/models --collect-only -q` collects 667 nodes at `origin/develop`
and 670 at this head after the develop sync (baseline
`docs/testing/inventory/baseline.json` formal/ = 664 plus open deltas; the +3
above is this branch's formal/ delta). The counts moved with develop; the delta
did not. One additional node lands in `tests/`: `tests/test_postgres_health_checks.py`
parametrizes one case per workflow that declares a Postgres service, and
`formal-conformance-nightly.yml` adds the nightly service
(`formal-conformance-nightly.yml:formal-nightly:postgres`), hence the
`tests/: +1` delta above. Like I29, the machine is about the PostgreSQL
store, so it skips without `MAISTRO_TEST_PG_DSN`; `formal-conformance.yml`
and the nightly workflow both provision the service, so nothing skips in CI. Runs at the PR budget in ~4-8s; measured
60-example run 17.6s, so nightly budgets for this module should stay on the
`MAISTRO_FORMAL_PG_EXAMPLES` knob rather than the default 10k.

The six-mutant demonstration battery and the research disposition live in
`docs/research/881-execution-lifecycle-state-machines.md`.
