---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +9
---
# 1238-state-write-acknowledgment

## What changed

`State._writer_loop` caught every exception after a write had been accepted —
log, roll back, move on — and nothing in the queue carried an outcome, so no
submitter could ever learn that a commit failed. Hive's `ModelStore` /
`JsonStore` mutated memory and then fired an unacknowledged
`PersistedStore.put/delete/put_raw`, so a successful HTTP response could
describe a mutation the database had refused: the mutation silently
disappeared after restart, or a "deleted" record resurrected.

- `packages/maistro-core/src/maistro/state.py`: queued items now carry a
  completion signal (`_Tx`); new `State.submit_sync()` blocks until the writer
  thread has committed and re-raises its failure; `PersistedStore.put`,
  `delete`, and `put_raw` are acknowledged writes. Fire-and-forget `submit`
  keeps its non-raising contract, and `flush()` stays an error-free drain
  barrier.
- `packages/hive-conductor/backend/services/model_store.py`:
  `ModelStore.__setitem__` and `JsonStore.__setitem__` persist before mutating
  memory, so a refused write raises to the caller with memory still coherent
  with disk (`pop` already deleted before popping, keeping the parent
  addressable/retryable).

## Tests

- `packages/maistro-core/tests/state/test_write_acknowledgment.py` (+9): a
  commit-failing connection proxy isolates the exact reported failure mode —
  `fn` succeeds, `COMMIT` raises — and asserts the error reaches the
  `submit_sync`/`put`/`delete`/`put_raw` caller with the failed transaction
  rolled back and the writer loop still alive; restart probes show the failed
  put absent and the failed delete's record not resurrected; fire-and-forget
  `submit`, timeout, and after-close refusals pin the surrounding contracts.
  Every raising case fails against the pre-fix writer loop, which reported
  nothing to anyone.
- `packages/hive-conductor/backend/tests/test_model_store_svc.py` (+3): with a
  persisted double whose writes raise, `ModelStore`/`JsonStore` `__setitem__`
  leave memory unchanged and `pop` leaves the record addressable — the
  in-memory half of the acknowledgment contract.
