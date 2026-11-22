---
inventory-delta:
  packages/maistro-core/tests: +11
  packages/maistro-server/tests: +4
---
# 1242 two-worker and receipt-surface regressions

Issue #1242 (task cancellation reported success without stopping running
work). This round finishes the receipt contract with evidence at the two
altitudes the earlier receipt regressions did not reach: a real second worker
process, and the public receipt surfaces.

`packages/maistro-core/tests` (+9):

- `runs/test_pg_two_worker_cancellation_1242.py` (+3, PG-gated, skipped
  without `MAISTRO_TEST_PG_DSN`): two real OS workers on one migrated
  PostgreSQL. A worker that owns the provider cancels from another process and
  must report `STOP_PENDING` — the fence is durable, the stop is not — while
  the owner's late success is refused by the durable fence (Attempt ends
  `CANCELLED`, never `COMPLETED`). A SIGKILLed owner stays `STOP_PENDING`
  until lease reclaim settles it, and only then may a receipt say
  `STOP_CONFIRMED`; a restarted worker sees the fence, not a fresh Run.
  Requires Docker compose PG plus `uv run alembic upgrade head`; it does not
  run in the default CI leg without `MAISTRO_TEST_PG_DSN`.
- `runs/test_cancellation_receipt_1242.py` (+2): the receipt's completion-race
  semantics — a fence that loses to a completing Run reports the winner's own
  status (`COMPLETION_WON`, `fenced=False`), and an already-completed Run's
  repeat cancellation claims no stop and no fence.
- `tasks/test_cancel_receipt_1242.py` (+6): `TaskQueue.cancel_receipt` — the
  task receipt agrees with the Run receipt (queued cancel proves no physical
  try existed; in-flight under a remote lease reports `STOP_PENDING` and
  names the holder; a terminal receipt refuses with `COMPLETION_WON`; an
  admitter probed as lacking `cancel_run_receipt` degrades to `UNCERTAIN`,
  never borrowed confidence; unknown task is `None`, the route's 404).

`packages/maistro-server/tests` (+4):

- `api/test_cancellation_receipts_1242.py`: the wired FastAPI routes now
  expose the receipt fields — `POST /runs/{id}/cancel` carries
  `fenced`/`stop_confirmed`/`disposition`/`cause`/`diagnosis`/`attempts`
  (confirmed for a queued Run, `stop_pending` naming the remote holder for an
  in-flight one), and `DELETE /tasks/{id}` carries
  `disposition`/`stop_confirmed`/`diagnosis`/`run_id` with refusals still the
  route's 400.

Mutation evidence: reporting a live remote try as `STOP_CONFIRMED` in
`maistro.runs.cancellation.classify_attempt` fails the in-flight regressions
at both the queue and Run altitudes; the production file was restored
byte-for-byte afterwards. The three Conductor cancel-route tests pinned to the
old exact 3-field response were updated to assert the new receipt fields on
the same in-process-confirmed path (no count change).
