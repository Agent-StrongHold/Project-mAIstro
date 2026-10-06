---
inventory-delta:
  packages/hive-conductor/backend/tests: +12
---

# #1332 Chat-launched DAG runs are cancellable: correlation at canonical admission

`_tool_run_workflow` opened its Recent Runs projection under a fresh execution
id and never recorded the canonical `run_id`, so `POST /v1/dag-runs/{id}/cancel`
sent the projection id to the canonical store and answered 404 while the DAG
kept running. The fix adds an `on_admitted` admission seam to
`canonical_dag_runner.execute_dag` (fired after `create_run`, before any
physical node work), a `DagRunStore.record_canonical_run` write (first link
wins, persisted), and a producer-side cancellation path that follows the
canonical cancel fence without mistaking a chat-disconnect teardown for a DAG
cancellation.

+12 collected node IDs on `packages/hive-conductor/backend/tests`
(`test_chat_launched_dag_cancel.py`):

- the production-path regression: a real chat-launched DAG held in flight after
  canonical admission, listed, and cancelled **by its projection id** with no
  test-seeded mapping — the parked provider unwinds, Run/NodeRun/Attempt settle
  CANCELLED, a non-member's cancel is 404-refused before any canonical
  mutation, and the row follows canonical cancellation;
- the mapping survives a store reopen (durable `records` round-trip) and the
  shipped read route resolves it;
- missing admission (no canonical Container) and failed admission (refusing
  `create_run`) both leave a row with an empty correlation that the cancel
  route refuses — no falsely cancellable success record;
- the admission sink itself: exactly one call with the admitted id while the
  Run is still QUEUED, never invoked without a canonical store, and a raising
  sink never fails an execution the spine already admitted;
- `record_canonical_run` unit behavior: persisted, reopen-stable, missing-row
  and empty-id refusals, idempotent same-id, first-link-wins.

The main regression was shown to fail against the pre-fix producer (the
projection write suppressed): it times out on "chat-launched row never
recorded its canonical admission" instead of passing.
