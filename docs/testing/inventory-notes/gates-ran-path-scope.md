---
inventory-delta:
  tests/test_check_gates_ran.py: +3
  tests/test_gates_ran_publisher_contract.py: +1
---

# Gates-ran path-scoped execution evidence

Added four regression tests for the generalized path-scoped skip contract:

- a non-specialized mapped check may be explicitly skipped only when measured
  out of scope;
- out-of-scope failures remain findings;
- an unmeasured scope keeps a mapped skip pending; and
- the publisher delegates evaluation to the checked-in evaluator with its
  changed-file envelope (rather than an inline heredoc).

No existing test node IDs were removed or renamed.
