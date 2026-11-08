---
inventory-delta:
  tests/: +2
---

# #860 — soak promotion-gate regression coverage

`tests/test_soak_promotion_gates.py` adds two root-suite nodes for the pure
`failed_promotion_checks` evaluator. They prove that H4/H5/H6, the observed
soak duration, and a required graceful drain all change the driver exit result,
and that an explicit SIGKILL probe does not falsely claim a graceful drain.
