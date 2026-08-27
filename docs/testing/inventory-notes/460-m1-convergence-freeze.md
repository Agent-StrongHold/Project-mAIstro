---
inventory-delta:
  tests/: +4
---

# M1 convergence-freeze test delta

Issue #460 adds four root tests for the no-new-islands policy: rejection of an unapproved subsystem, the explicit exception path, convergence by removing a legacy island, and the live pull-request comparison against the checked convergence matrix.
