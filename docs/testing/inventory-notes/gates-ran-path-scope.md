---
inventory-delta:
  tests/: +4
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
