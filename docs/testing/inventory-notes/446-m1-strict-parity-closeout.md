---
inventory-delta:
  tests/: +1
---

# M1 strict parity closeout

Issue #446 adds one regression test for the #459 closeout contract. Normal
parity development still records named dependency blockers while product
convergence lands, but `M1_STRICT_CLOSEOUT=1` now rejects those blocker-only
passes. The strict invocation therefore cannot report M1 parity evidence while
a required producer or observer scenario abstains.
