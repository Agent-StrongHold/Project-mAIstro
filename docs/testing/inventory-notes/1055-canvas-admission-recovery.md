---
inventory-delta:
  packages/maistro-canvas/tests/test_canonical_executor_integration.py: +1
---

# #1055 Canvas admission recovery evidence

Adds a restart-shaped fault injection test for the crash window after canonical
Run admission and before Canvas receipt persistence. It proves the runner's
canonical-fact reconciliation recreates the receipt and that an idempotent retry
returns the same receipt/Run instead of admitting a second execution identity.
