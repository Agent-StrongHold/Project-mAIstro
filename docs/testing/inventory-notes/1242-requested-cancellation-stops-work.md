---
inventory-delta:
  packages/maistro-core/tests: +10
---

# #1242 — a requested cancellation stops the running work

`DELETE /tasks/{id}` went through `TaskQueue.cancel`, which terminalized the
receipt and reported success while the runner's coroutine ran on: the executor
the caller cancelled kept consuming compute and writing into the workspace, and
when it eventually finished, its result was attached to a receipt that already
said CANCELLED. The queue had no handle to the physical work, so a cancellation
could only rewrite the receipt.

The fix gives the queue a registry of in-flight executions: the runner registers
the `asyncio.Task` dispatching each claimed task and unregisters it from that
task's own done callback, and `TaskQueue.cancel` cancels the registered
execution and waits (bounded by `CANCELLATION_SETTLE_TIMEOUT`) for the
`CancelledError` handlers to finish before answering. The unwinding work no
longer fights the receipt: both `claim()`'s exception path and the worker's
`CancelledError` handler distinguish a *requested* cancellation (receipt already
CANCELLED — leave it, it is the truth the caller acted on) from a shutdown
cancellation (receipt not terminal — keep recording
`Task cancelled during shutdown` exactly as before).

## Reconciliation with the canonical cancellation path (#1320)

Develop independently fixed the same class end to end through the canonical
model (#1169/#1320): `TaskQueue.cancel` calls `admitter.cancel_run(run_id)`
first, which fences the Run CANCELLED and signals the in-process owner of the
physical Attempt. Merging the two branches kept both halves:

* For admitted work the canonical Run is cancelled first — the receipt is a
  projection and follows afterwards. The registry stop still applies to work
  this queue dispatched itself, including deployments with no admitter, where
  no Run exists to carry the signal.
* The canonical stop delivers its `CancelledError` to the worker *before* the
  receipt flips to CANCELLED (the Run is cancelled first and the runtime
  settles the victim inside `cancel_run`). The worker's shutdown branch
  therefore also guards `set_result` behind the FAILED transition: when the
  already-CANCELLED Run refuses that transition, nothing is written, and the
  receipt records the requested cancellation with no result — pinned by the
  `receipt.result is None` assertion in
  `test_a_requested_cancellation_records_a_cancelled_attempt_and_run`.

## The tests

Ten tests in `packages/maistro-core/tests/tasks/test_requested_cancellation.py`:

- `test_cancel_stops_the_running_work` — the regression. Proves the failure
  mode on the unfixed tree (executor completed after `cancel()` returned True;
  a result landed on the cancelled receipt) and its absence on the fixed one.
- `test_a_cancelled_receipt_keeps_no_result_after_the_work_stopped` — the
  secondary defect isolated: the executor observes its `CancelledError` at
  cancel time and the receipt keeps `result is None`.
- `test_a_requested_cancellation_records_a_cancelled_attempt_and_run` — the
  canonical spine must agree with the receipt: Attempt CANCELLED (via the
  existing `CancellationCause.REQUESTED` reconciliation), NodeRun cancelled,
  Run CANCELLED, all driven through `queue.cancel` — the product path, not the
  never-wired `TaskAttemptExecutor.cancel`.
- `test_cancel_does_not_report_success_before_work_settles` — a
  cancellation-suppressing executor keeps the cancellation response from
  claiming success while it remains alive, and cannot attach a later result.
- `test_cancelled_work_cannot_attach_a_late_failure` — work that handles
  cancellation and then raises cannot attach a late error result to the
  already-cancelled receipt.
- `test_cancel_reaches_work_still_waiting_for_a_lane` — a dispatched task
  parked at the lane gate is stopped too, and the gate's handed-permit
  cancellation branch is exercised end to end.
- `test_cancel_a_queued_task_and_it_never_starts` — no registered execution
  yet: the receipt transition still succeeds and the dispatcher refuses the
  stale dequeue.
- `test_cancelling_finished_work_reports_false` — terminal work cannot be
  cancelled; the response must not claim a cancellation that did not happen.
- `test_shutdown_cancellation_still_records_a_failure` — the shutdown
  semantics are pinned so the requested/shutdown distinction cannot swallow
  them.
- `test_the_execution_registry_does_not_retain_finished_work` — unregistration
  runs from the done callback; no stale handle survives a completed task.

Verified to bite: with the source fix reverse-applied (tests kept), six of
these fail — the regression, the settle-timeout honesty, the late-failure
defect, the spine disagreement, the registry mechanism, and the
result-attachment defect — and the four guard tests pass, matching the paths
the transition refusal already protected.

## Independent verification (head 10a49a14, 2026-09-10)

Re-executed at the exact head, not taken from the implementing run:

- `uv run pytest packages/maistro-core/tests/tasks/test_requested_cancellation.py -q`
  → 10 passed.
- `uv run pytest packages/maistro-core/tests/tasks -q` → 256 passed;
  `packages/maistro-server/tests/api/test_tasks.py test_tasks_run_identity.py`
  → 28 passed (DELETE /tasks/{id} → 400 on refused cancellation).
- Bite check in a throwaway copy of the head with the `queue.py`/`runner.py`
  hunks reverse-applied (tests kept): 6 failed / 4 passed, the six listed
  above; the primary regression fails with the executor completing after
  `cancel()` returned True.
- `uv run ruff check .` clean; canonical six-package `uv run mypy` clean;
  `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` ok.
- Full `packages/maistro-core/tests` on this host: 9475 passed; the 46
  failures are environmental, both pre-existing and untouched by this diff —
  21 bwrap sandbox probes (`Resource temporarily unavailable`: the backend
  applies `RLIMIT_NPROC` to bwrap itself pre-exec, which fails under this
  host's process load; CI documents the same class of bwrap namespace
  failure) and 25 postgres-leg tests against the shared host container,
  which runs PostgreSQL 16 below the `MIN_POSTGRES_VERSION = 17` floor that
  the develop base already sets at `container.py:1798`. The postgres-leg
  failures were additionally flaky run-to-run (shared container under
  concurrent load) and pass when the container is quiet.
- No premature GitHub closure keywords (`fixes/closes/resolves`) in any
  commit message on 551c38b5..10a49a14.
