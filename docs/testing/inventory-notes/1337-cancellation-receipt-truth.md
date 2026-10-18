---
inventory-delta:
  packages/maistro-core/tests: +3
---
# Cancellation receipt truth (#1337)

## Scope

A user-initiated `TaskQueue.cancel` on in-flight work fences its canonical Run
CANCELLED and signals the Attempt's runtime owner, so the worker settles
through `_run_with_permit`'s `CancelledError` handler. That handler used to
write the "Task cancelled during shutdown" disposition unconditionally: the
FAILED transition was refused by the already-CANCELLED Run (and reconciled per
#849), but `set_result` and the progress webhook fired anyway, leaving a
cancelled receipt carrying a shutdown failure that never happened and pushing
it to the webhook.

Two production writes are affected, and both now follow the same rule — write
the failure result only when the failure transition was accepted, then emit
the actual receipt state:

- `TaskRunner._run_with_permit` gates `set_result` on `update_status`'s
  return value, and still emits either way (the receipt read at emit time is
  whichever disposition actually holds).
- `TaskQueue.claim`'s `BaseException` handler no longer writes the FAILED
  disposition for `CancelledError` at all: on a Run that refuses the
  transition it clobbered the reconciled projection with
  `str(CancelledError)` — an empty error — and in the no-Run case it ran
  before the runner's handler, swallowing the shutdown text the handler is
  responsible for. `claim`'s only production caller is the runner; ordinary
  exceptions keep the fail-fast disposition (`test_claim_exception_marks_task_failed`
  is unchanged and still passes).

No second cancellation marker, no cancellation-cause policy, and no Run or
Attempt layer change is included. On the wired stack a drain cancellation is
already carried up to the Run by the Attempt reconciliation
(`CancellationCause.REQUESTED`), so the receipt reads CANCELLED there too;
only the plain-queue (no admitter) drain keeps the literal shutdown failure.

## Three additive cases

`packages/maistro-core/tests/tasks/test_runner_cancellation_receipt.py` drives
the real public path — admission (`TaskRunAdmitter` over `InMemoryRunStore`),
the Attempt seam (`TaskAttemptExecutor`), Runtime, and runner — with a
recording webhook sink and a blocking executor; no method patching:

- User cancel through `TaskQueue.cancel` while the executor is in flight: the
  receipt must read CANCELLED, the Run CANCELLED, and neither the receipt's
  result nor any webhook payload may claim "Task cancelled during shutdown";
  the final payload reports the cancelled state.
- `TaskRunner.stop(drain_timeout=0)` on the wired stack: the worker settles,
  the Run layer records a cancellation, and the receipt/webhook again carry
  no shutdown claim.
- `TaskRunner.stop(drain_timeout=0)` on a plain queue (no admitter, no
  Attempt seam): the positive control. The receipt must still read FAILED
  with exactly "Task cancelled during shutdown", and the webhook must still
  receive it — the shutdown branch is preserved, not deleted.

## Failure evidence

With production reverted to the parent commit (`git show HEAD:` over the two
source files, fixed copies held aside), the two wired cases fail — the
cancelled receipt and the webhook carry "Task cancelled during shutdown" —
while the plain-queue control passes. With the fix applied, all three pass.
Existing suites unchanged: `tasks/` (486 passed, 17 skipped), `runs/` (1128
passed, 248 skipped), `test_queue.py`, and the runner-consuming
`maistro-server` shutdown/recovery/quota-ledger suites.

```text
uv run pytest packages/maistro-core/tests/tasks/test_runner_cancellation_receipt.py packages/maistro-core/tests/tasks/test_runner.py packages/maistro-core/tests/tasks/test_runner_run_refusal.py -q
```
