---
inventory-delta:
  packages/maistro-core/tests: +6
---
# 1151 running-run reconciliation

Six tests in `tests/graph/durable_runs/test_canonical_durable_store.py` cover:

- terminal NodeRuns settling a canonical `RUNNING` Run without a new Attempt;
- a `RUNNING` continuation with `resume_at=None` becoming due;
- terminal `FAILED` continuation state settling a stranded canonical Run;
- stale continuation status being repaired from a terminal canonical Run;
- a missing continuation remaining absent rather than violating the checkpoint authority ADR;
- the checkpoint-1 `QUEUED` continuation / canonical `RUNNING` window.

The transient completion-write retry test from the earlier draft was dropped during
the develop sync: develop's #1288 contract
(`tests/runs/test_chat_execution.py::TestAPostDispatchRecordingFailureIsNeverRedispatched`)
requires a post-dispatch record failure to surface as `ChatDispatchUnrecorded`
with the Attempt left RUNNING for the recovery sweep, so `AttemptExecutionService._terminalize`
must not retry the write in-line. The stranded-Attempt window is instead settled by the
canonical RUNNING reconciliation sweep and the `attempt_executor` active-Attempt guard.
