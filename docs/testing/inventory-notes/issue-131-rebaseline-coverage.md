---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-server/tests: +2
---
# Issue #131 re-baseline coverage repair

Re-baselining the lane onto develop (post-#1280/#1306) left four changed source
lines uncovered in the two files the diff-coverage floor scores per file, and
the floor is per file, not pooled:

- `Container._sweep_chat_runs` — the no-admitter early return and the sweep
  failure arm. One core case closes a Run with `chat_admitter = None`; one
  proves a raising sweeper still leaves the close successful and the Run
  COMPLETED (retention is housekeeping, never the turn's outcome).
- `chat_completions._admit_turn` — the `except asyncio.CancelledError` arm on
  the API's direct-admit path (the seam's own #1280 compensation never sees
  this Run). One server case cancels the QUEUED transition and asserts the
  persisted Run is compensated to CANCELLED with `ADMISSION_INCOMPLETE` before
  the error propagates; one proves a cancellation before persistence
  compensates nothing and persists nothing.

Both additions drive real stores and the real admission/close paths; the only
doubles are the boundary forcing functions (an admitter whose `sweep` raises,
a cancelled first transition), mirroring the file's existing `_BrokenAdmitter`
precedent.
