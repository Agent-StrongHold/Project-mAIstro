---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  tests/: +1
---

# M1 strict parity closeout

Issue #446 keeps the #459 closeout contract fail-closed and executes the
Builders, scheduler, and Evolve producer paths against canonical Run,
NodeRun, and Attempt stores. Normal parity development may record named
dependency blockers, but `M1_STRICT_CLOSEOUT=1` rejects blocker-only passes.
CI registers that strict invocation as a dedicated step, so it cannot report
M1 parity evidence while a required producer or observer scenario abstains.
