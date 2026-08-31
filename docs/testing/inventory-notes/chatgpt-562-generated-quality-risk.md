---
inventory-delta:
  tests/: +10
---

# Typed quality-state autonomous-merge policy

Adds ten focused root-suite regressions for #562. The original eight prove the first
trusted-base-derived quality ledger is YELLOW rather than RED, merge groups may
carry that YELLOW evidence after PR-time policy, specification and unmigrated
legacy state remain RED, and unknown, malformed, or ambiguous classifications
fail closed.

Two closeout regressions cover the branches identified by diff coverage without
weakening its floor: every malformed registry shape is exercised through the
fail-closed parser, and the real script entrypoint is executed as a CLI against a
temporary Git repository.

The migration case pins `wiring-reads-baseline` as `base_derived`, with no
`target_kind`, and outside the frozen legacy aggregate set.
