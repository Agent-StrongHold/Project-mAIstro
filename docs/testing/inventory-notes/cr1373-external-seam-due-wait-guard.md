---
inventory-delta:
  packages/maistro-core/tests: +2
---

# CR1373 external-seam due-wait guard

M1-E2 (#1373) recovery acceptance: `wake_due_registered_dag_runs` polls
cross-instance peer/harness completions through `poll_external_results`, and
the walker's fenced `agent.spawn_harness` poll settles the same parked receipt
when the timer elapses. A wait whose own `resume_at` had already elapsed was
therefore read twice in one tick — once by the external seam and once by the
walker — and the external result was then discarded.

`poll_external_results` now defers a `WAITING` wait whose `resume_at` is elapsed
to `resume_due_graph_runs`; a completion that lands *before* its timer is still
this seam's ingress.

- `packages/maistro-core/tests/graph/durable_runs/test_m1_e2_recovery_convergence.py`
  (+2): `test_the_external_seam_defers_a_due_timer_wait_to_the_timed_resume`
  pins the deferral (returns 0, no provider read), and
  `test_the_external_seam_drains_a_completion_that_lands_before_the_timer`
  pins the preserved early-completion ingress (returns 1, provider read once).

Fail-before evidence: with the `_is_timed_wait_due` guard disabled, the first
case fails `assert 1 == 0` (the external seam reads the due wait); both cases
pass with the guard. The develop-pinned end-to-end regression
`test_registered_harness_completion_uses_the_production_timer_and_fresh_resolver`
(`packages/hive-conductor/backend/tests/test_registered_dag_recovery.py`) failed
`{'poll': 2} != {'poll': 1}` before this change and passes after it.
