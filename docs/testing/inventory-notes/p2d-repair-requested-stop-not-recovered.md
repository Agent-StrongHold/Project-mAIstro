---
inventory-delta:
  packages/maistro-core/tests: +1
---

# P2d repair follow-up: pin that a requested stop never routes through the seam (#2369 / #232)

Independent validation of the P2d acceptance criterion "CancelledError stays
REQUESTED" found the guarantee structural only: `_terminalize_if_open`'s guard
(`current.status is CREATED and status is not CANCELLED`) is what keeps a
requested cancellation out of `compensate_unlaunched_attempt`, and no test
executed a requested-stop settle against a CREATED attempt. The pre-existing
cancel-during-launch test cannot serve: its cancellation lands after the
RUNNING claim, so it never crosses the guard.

## Collected node IDs

`packages/maistro-core/tests/runs/test_execution.py` (+1):

- `test_a_requested_cancelled_prelaunch_settle_never_routes_through_the_seam`:
  feeds `_terminalize_if_open` the CancelledError disposition (status
  CANCELLED) on a CREATED attempt and asserts the ordinary terminalize path —
  `owned is True`, CANCELLED with no RECOVERED cause, still unstarted,
  finished_at stamped, persisted cause stays None, and the instrumented store
  records zero `compensate_unlaunched_attempt` calls.

## Mutation evidence

With the guard's `and status is not AttemptStatus.CANCELLED` clause removed
(every CREATED settle routed through the seam), the new test fails; with the
guard restored it passes. The regression it names is reachable by a one-line
change, not a hypothetical.
