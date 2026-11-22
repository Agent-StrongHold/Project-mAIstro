---
inventory-delta:
  packages/maistro-canvas/tests: +21
---

# #1055 Canvas admission recovery evidence

Repairs the crash window between canonical Run admission and Canvas receipt
persistence, and replaces two tests that asserted the old (compensating)
failure semantics:

- Removed `test_admission_rolls_back_run_when_queue_transition_fails` and
  `test_receipt_persistence_failure_leaves_run_...`'s predecessor
  `test_receipt_persistence_failure_compensates_admitted_run`: admission no
  longer compensates (deletes) an admitted canonical Run when the Canvas
  receipt write fails — compensating a durable Run is exactly what produced
  admission-receipt divergence after a crash.
- Added `test_admission_is_queued_in_the_single_canonical_write` (the queue
  transition happens inside the single canonical write, not as a follow-up
  step), `test_receipt_persistence_failure_leaves_run_for_durable_reconciliation`
  (a failed receipt write leaves the admitted Run in place), and
  `test_restart_reconciles_admission_gap_and_idempotent_retry_reuses_run`
  (restart reconciles the receipt gap; an idempotent retry returns the same
  receipt/Run instead of admitting a second execution identity).

Net: +21 collected node IDs on `packages/maistro-canvas/tests`, including
restart, reconciliation, idempotency, and integrity-path coverage.
