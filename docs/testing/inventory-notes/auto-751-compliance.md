---
inventory-delta:
  tests/: +12
---

# Issue #751 compliance evidence validator

Adds twelve collected regression tests for the standalone compliance claim/evidence
validator. The tests cover malformed rows, required claim identity fields,
missing evidence, disabled/manual-only/stale/failing evidence, and a valid
current evidence record. This validator is intentionally not wired into CI.
