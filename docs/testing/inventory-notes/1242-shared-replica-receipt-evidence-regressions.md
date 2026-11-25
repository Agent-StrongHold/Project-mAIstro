---
inventory-delta:
  packages/maistro-core/tests: +11
---
# 1242 shared-replica and receipt-evidence-surface regressions

Issue #1242 repair round at `1d65cee98cc2`: CI's diff-coverage gate measured
changed receipt-surface lines that no producer executed — the admitter
receipt routes (`TaskRunAdmitter.cancel_run_receipt`'s unknown-run None,
`WorkspaceRoutingAdmitter.cancel_run_receipt` in full), the shared-tier half
of `TaskQueue.cancel_receipt` (a replica holding no local receipt: settle on
the admitter's evidence, refuse an already-settled run, degrade to UNCERTAIN
without evidence), the `_unevidenced_receipt` refusal and no-Run-identity
shapes, the `_run_cancel_receipt` guard, the silent-receipt None, and
`AttemptExecutionService.cancel_registered_evidence`'s registered-owner arc.

Ten regressions, all over the real in-memory canonical store and the real
`TaskQueue`/admitter wiring, plus one over the real `TaskRunner`:

- `tasks/test_cancel_receipt_1242.py` +8 — second-replica settle/refuse/
  uncertain, unevidenced refusal, no-Run-identity stop, the evidence guard,
  the foreign-run None, the Workspace router's receipt routing.
- `tasks/test_runner_cancellation_receipt.py` +1 — a dispatched receipt-only
  task (no Run identity, live executor coroutine) cancelled through the
  receipt path answers UNCERTAIN, never a confirmed stop; executed
  failing-before against the prior `STOP_CONFIRMED` behavior at head
  `1d65cee98cc2`.
- `runs/test_execution.py` +2 — `cancel_registered_evidence` answers `None`
  only when no service owns the try, and answers the owner's bool when it
  does; the second pins the contract the classifier's stop aggregation reads.

No production code changed in this round; the receipts were already
truthful — nothing measured them at these altitudes.
