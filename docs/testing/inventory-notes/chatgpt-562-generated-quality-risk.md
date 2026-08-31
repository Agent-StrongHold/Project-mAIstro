---
inventory-delta:
  tests/: +8
---

# Typed quality-state autonomous-merge policy

Adds eight focused root-suite regressions for #562. They prove the first
trusted-base-derived quality ledger is YELLOW rather than RED, merge groups may
carry that YELLOW evidence after PR-time policy, specification and unmigrated
legacy state remain RED, and unknown, malformed, or ambiguous classifications
fail closed.

The final case pins the migration itself: `wiring-reads-baseline` is
`base_derived`, has no `target_kind`, and is no longer part of the frozen legacy
aggregate set.
