---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +29
---

# CR1373 external-seam due-wait guard and diff-coverage repair

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
  (+15): `test_the_external_seam_defers_a_due_timer_wait_to_the_timed_resume`
  pins the deferral (returns 0, no provider read), and
  `test_the_external_seam_drains_a_completion_that_lands_before_the_timer`
  pins the preserved early-completion ingress (returns 1, provider read once).
  The remaining thirteen pin the seam's reachable edges: non-positive limit,
  a raising provider, pauses without an external waker, malformed pause
  records, the WAITING-scoping of the deferral (a PAUSED pause with an
  elapsed timer is still seam-polled), a store-refused receipt, injected
  harness completions (success and failure) and an unregistered harness
  type, peer metadata without a destination, the `Container` A2A receipt
  waker (canonical write, unroutable receipts, a stale receipt, and the
  scheduler's no-running-loop warning), and the stranded-run sweep's
  non-evidence skips.
- `packages/maistro-core/tests/graph/durable_runs/test_stores_gaps.py` (+7):
  the external-result envelope validation branches (delivery, identical
  replay, conflicting replay, missing run, invalid envelopes), the SQLite
  external-result mutation, `list_hitl_due`'s post-authorization limit, and
  `_earliest_wakeup`'s malformed sibling pauses.
- `packages/maistro-core/tests/graph/durable_runs/test_cross_store_crash_reconciliation.py`
  (+1): the canonical seam returns the persisted Run, replays an identical
  receipt as a no-op, and refuses unknown runs.
- `packages/maistro-core/tests/a2a/test_guest_peers.py` (+2): the peer task
  status reader — destination guards, terminal mapping, 404, running tasks,
  and uncertain transport.
- `packages/maistro-core/tests/a2a/test_delegate.py` (+2): the A2A receipt's
  completion handler — absent handler, and a handler that raises without
  corrupting the durable receipt.
- `packages/hive-conductor/backend/tests/test_dag_recovery.py` (+2) and
  `test_registered_dag_recovery.py` (+2): the wake ticks' two halves —
  delegation surfaces poll before the timed resume, an empty poll does not
  gate the timer, containers without surfaces never poll, and a delivered
  completion sends the queued parent to the recovery half.

Fail-before evidence: with the `_is_timed_wait_due` guard disabled, the first
case fails `assert 1 == 0` (the external seam reads the due wait); both cases
pass with the guard. The develop-pinned end-to-end regression
`test_registered_harness_completion_uses_the_production_timer_and_fresh_resolver`
(`packages/hive-conductor/backend/tests/test_registered_dag_recovery.py`) failed
`{'poll': 2} != {'poll': 1}` before this change and passes after it.

Coverage evidence: the branch's diff-coverage gate (per-file lines ≥90%,
branch arcs ≥80% against the merge base) failed on 9 production files at
865452597. After these tests, `scripts/check-diff-coverage.py` over the
CI-shaped producers (`coverage run --branch --source=packages/maistro-core/
src/maistro -m pytest packages/maistro-core/tests` and the hive-conductor
backend producer) names no failing file.

Delta arithmetic: the recorded core delta is +29 while this round added 27
collected tests. The +2 absorbs two sibling notes whose movements are already
inside origin/develop's current baseline — `cr1373-external-result-crash-window`
(+1) and `auto-62-5dad` (−3, net −2) — so the branch's notes sum to the true
+27 collection delta and integration folds cleanly.
