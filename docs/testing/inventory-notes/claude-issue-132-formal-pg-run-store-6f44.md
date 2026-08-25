---
inventory-delta:
  formal/: +1
---
# claude-issue-132-formal-pg-run-store

One node ID: `formal/models/test_run_lease_fence.py::TestRunLeaseFenceMachine`.
A Hypothesis `RuleBasedStateMachine` collects as a single test regardless of how
many examples or steps it explores, so `+1` here buys a few hundred generated
interleavings rather than one case.

It is I29 — the execution lease and fence, against the real `PgRunStore` — and
it is #132's remaining acceptance criterion, `formal/ property tests pass
against the PostgreSQL store`.

Three rules drive the lifecycle (`start_attempt`, `begin_running`,
`leave_running`, `cancel_before_running`) and two attack the fence: an absent
token, and a *retired* one replayed from an earlier Attempt. Three invariants
hold throughout: at most one active Attempt, the store agreeing with the model
about which Attempt is active and in what status, and ordinals contiguous from
one.

`formal-conformance.yml` gains a PostgreSQL service in the same change. That is
not incidental: `scripts/ac_outcome_plugin.py` counts a skipped test as no
evidence, so a model gated behind an unset DSN would leave the criterion
unproven however green the job looked.
