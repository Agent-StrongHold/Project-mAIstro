---
inventory-delta:
  tests/: +18
---

# Issue #751 compliance evidence validator

Adds eighteen collected regression tests for the standalone compliance claim/evidence
validator. The tests cover malformed rows (including a missing leading pipe), missing
status cells, required
claim identity fields, missing evidence, disabled/manual-only/never-run/stale/missing/
failing evidence, cited-path coverage, and a valid current evidence record. This
validator is intentionally not wired into CI.
