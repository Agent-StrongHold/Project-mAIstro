---
inventory-delta:
  packages/maistro-core/tests: +3
---
# auto-1242 net suite-inventory correction

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Net reconciliation for issue #1242's `packages/maistro-core/tests` regressions,
recorded at head `824b1b61a2`. The branch's three new test files collect 18
node IDs on this tree (`runs/test_cancellation_receipt_1242.py` 9,
`runs/test_pg_two_worker_cancellation_1242.py` 3 (PG-gated, collected as
skips), `tasks/test_cancel_receipt_1242.py` 6), while the two earlier
per-round notes (`1242-cancellation-receipt-regression.md` +4 and
`1242-two-worker-and-receipt-surface-regressions.md` +9) recorded the counts
as of the heads that introduced them. Two later rounds grew the receipt file
(the completion-race pins of `52d59827ab` and the reclaim-evidence rework of
`859eeb1a79`) and the second develop merge (`c730cce8c3`) replaced the
baseline, so the recorded deltas no longer summed to collection. This note is
the arithmetic remainder only (+3): no test was added or removed by this
repair round, and the other 20 suites check clean against their sums.

## Repair round (this note's change)

Two repairs, both against executed evidence, no production change:

1. **Suite inventory.** The pre-worker validation failed
   `scripts/check-suite-inventory.py` on `packages/maistro-core/tests`
   (expected 18894, collected 18897): the branch's earlier notes under-counted
   what the tree now collects. This note records the net +3.
2. **PG killed-owner leg encoded the pre-`859eeb1a79` semantics.** Run against
   a real pgvector pg18 container plus two real OS worker processes,
   `test_a_killed_owner_leaves_the_receipt_pending_until_reclaim_settles_it`
   still asserted `stop_confirmed=True` after lease reclaim — exactly the
   false stop `859eeb1a79` removed (reclaim writes CANCELLED+RECOVERED from
   lease expiry alone and never contacted the worker, so it cannot
   distinguish a dead worker from a partitioned one that kept executing).
   The test now pins the shipped semantics: after reclaim the receipt keeps
   `stop_confirmed=False`, `UNCERTAIN`, with the RECOVERED/reclaim diagnosis;
   the unit regressions `test_cancellation_receipt_1242.py` pin the same
   contract in-process. Mutation check: re-introducing the false stop
   (`classify_attempt` minting `STOP_CONFIRMED` for reclaim-settled rows)
   fails the repaired PG leg and three unit regressions; the production file
   was restored byte-for-byte afterwards. The stale prose in
   `1242-two-worker-and-receipt-surface-regressions.md` was corrected to
   match. Node count unchanged (same three tests, changed assertions).
