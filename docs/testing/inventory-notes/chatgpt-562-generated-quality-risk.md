---
inventory-delta:
  tests/: +11
---

# Typed quality-state autonomous-merge policy

Adds eleven focused root-suite regressions for #562. The original cases prove the
first trusted-base-derived quality ledger is YELLOW rather than RED, merge groups
may carry that YELLOW evidence after PR-time policy, specification and unmigrated
legacy state remain RED, and unknown, malformed, or ambiguous classifications
fail closed.

Closeout coverage now also proves the protected-base registry must satisfy the
canonical branch-independence schema before any quality surface can become
YELLOW: missing identity, missing rationale, invalid kind/path shape, a boolean
masquerading as schema version 1, and failure to load the canonical validator all
fail closed to RED.

The migration case pins `wiring-reads-baseline` as `base_derived`, with no
`target_kind`, and outside the frozen legacy aggregate set.
