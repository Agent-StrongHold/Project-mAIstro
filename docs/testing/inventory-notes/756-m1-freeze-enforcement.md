---
inventory-delta:
  tests/: +13
---

# PR #756 no-new-islands enforcement coverage

PR #756 adds thirteen collected root tests to the existing #460 convergence-freeze suite. The new cases prove that an exception label without a complete plan fails, #460 reuses the existing #36 lifecycle/model-egress/import vocabulary, planted Run/model-egress regressions are detected by those authoritative gates, new Workspace/Event/Checkpoint authorities are rejected outside canonical owners, canonical owners may extend their own concepts, explicitly marked product-local projections remain legal, existing legacy debt is not recharged merely because its file changes, the pull-request template carries the required review/exception fields, and both pull-request and merge-group events resolve the immutable event base SHA rather than a moving branch tip.

The pre-existing #460 tests for subsystem growth/shrinkage, live candidate comparison, and shallow-clone base resolution are updated in place and do not add to this delta.
