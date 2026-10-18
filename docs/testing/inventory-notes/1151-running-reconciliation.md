---
inventory-delta:
  packages/maistro-core/tests: +7
---
# 1151 running-run reconciliation

Six tests in `tests/graph/durable_runs/test_canonical_durable_store.py` cover:

- terminal NodeRuns settling a canonical `RUNNING` Run without a new Attempt;
- a `RUNNING` continuation with `resume_at=None` becoming due;
- terminal `FAILED` continuation state settling a stranded canonical Run;
- stale `RUNNING` continuation status being repaired from a terminal canonical `COMPLETED` or `FAILED` Run;
- a missing continuation remaining absent rather than violating the checkpoint authority ADR;
- the checkpoint-1 `QUEUED` continuation / canonical `RUNNING` window.

Disclosure: four of the seven are `xfail(strict)` characterization-of-gap nodes —
develop deliberately settles those windows through other reviewed paths (the
quiet-period observation guard, the resume-claim protocol, and the ordinary
walker re-queue). The terminal canonical Run repair and
`test_running_sweep_does_not_fabricate_missing_continuation` assert delivered
behavior. Each strict xfail flips the suite if develop later adopts the
behavior, forcing the marker's removal.

The transient completion-write retry test from the earlier draft was dropped during
the develop sync: develop's #1288 contract
(`tests/runs/test_chat_execution.py::TestAPostDispatchRecordingFailureIsNeverRedispatched`)
requires a post-dispatch record failure to surface as `ChatDispatchUnrecorded`
with the Attempt left RUNNING for the recovery sweep, so `AttemptExecutionService._terminalize`
must not retry the write in-line. The stranded-Attempt window is instead settled by the
canonical RUNNING reconciliation sweep and the `attempt_executor` active-Attempt guard
(`_frontier_has_active_attempt`); that guard's own regression pin lives in
`tests/graph/durable_runs/test_frontier_active_attempt_guard.py`
(see `1151-frontier-active-attempt-guard.md`).

This drop closes the lane's persistence-failure acceptance criterion through the
recovery path, not by an in-line retry: `packages/maistro-core/src/maistro/runs/execution.py`
is byte-identical to develop, and the criterion "persistence failure after successful
runtime execution does not silently discard the result, bypass node retry policy, or
leave an unrecoverable RUNNING Attempt" is what the #1288 contract tests already prove
on this tree — the answered turn is returned to the caller exactly once and logged,
the model is never asked again, and `recover_abandoned_attempts` reclaims the expired
lease and settles the stranded Attempt/NodeRun (executed at this head: the whole
`TestAPostDispatchRecordingFailureIsNeverRedispatched` class, 18 passed). PR #2153's
summary bullet claiming an idempotent terminal-write retry in `runs/execution.py` is
therefore stale branch history, not a description of this tree; correcting that body
is a GitHub-side edit outside worker authority and remains for the integrator.
