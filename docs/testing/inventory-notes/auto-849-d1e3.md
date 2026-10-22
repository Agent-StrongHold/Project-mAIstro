---
inventory-delta:
  packages/maistro-core/tests: +20
---
# auto-849-d1e3

#849 — task failure/completion receipts are durable, legal, and drain-safe.

Twenty additions, no removals and no parametrization changes:

- `tests/tasks/test_receipt_durability.py` (new, +15): the four edges the
  receipt contract was missing. Pre-PLANNING failure as a legal
  `QUEUED -> FAILED` transition with no gauge leak (and QUEUED -> COMPLETED
  still illegal); the runner shutdown drain landing scheduled TaskRecord
  writes (wait, cancel-on-stall, `stop()` after completion, `drain()`
  signal path); recovery projecting terminal receipts from the canonical
  Run (completed, failed, durable-write outage then restart); idempotence
  of that reconciliation; and the cancel-race semantics the reconciliation
  introduces (a receipt that flips CANCELLED mid-call is a win; a repeat
  cancel of an already-terminal receipt stays False for the route's 400).
- `tests/runs/test_consumption.py` (+4): the tick accounting breakdown —
  `TickAccounting` distinguishes attempted/succeeded/failed/parked/skipped,
  so a caught failure is never counted as a succeeded execution. Covers the
  node-failure park, an infrastructure exception raised to the tick, a
  successful tick, and a lost claim race.
- `tests/runs/test_parked_run_resume.py` (+1): the same honest accounting
  for the resume tick — a caught resume failure counts as `failed`, not as
  a resumed Run.

Existing tests updated in place (no count change): refusal-strand
expectations in `tests/tasks/test_admission.py` and
`tests/tasks/test_runner_run_refusal.py` now pin the reconciled projection,
and `tests/tasks/test_status.py` re-derives the machine with the new
`QUEUED -> FAILED` edge.
