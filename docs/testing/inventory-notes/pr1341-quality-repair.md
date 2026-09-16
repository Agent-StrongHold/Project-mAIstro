---
inventory-delta:
  packages/maistro-core/tests: +1
---

# PR #1341 quality repair

The quality gate on `b47c329b` stopped at Ruff's import-order error in
`scheduling/test_admission.py`; the existing `03d7e4ba` descendant fixes that
error. Once lint passed, the radon ratchet exposed three pre-existing HITL
reconciliation blocks in `canonical_store.py`. The repair extracts their
settlement parsing, terminal mirroring, and due-candidate filtering without
changing the canonical Run → NodeRun lifecycle.

Added `test_reconcile_cancelled_evidence_without_pause_detail` to pin the
legacy cancellation-evidence path: a terminal continuation with no `pause`
detail still repairs the canonical Run and NodeRun as `CANCELLED`, with no
fabricated answer. Existing durable-run tests continue to cover timeout
recovery, pagination, lost races, and attempt preservation.
