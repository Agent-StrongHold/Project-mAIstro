---
inventory-delta:
  tests/: +16
---

# Issue #751 compliance evidence validator

Adds sixteen collected regression tests for the standalone compliance claim/evidence
validator. The tests cover malformed rows (including a missing leading pipe), required
claim identity fields, missing evidence, disabled/manual-only/never-run/stale/missing/
failing evidence, cited-path coverage, and a valid current evidence record. This
validator is intentionally not wired into CI.
