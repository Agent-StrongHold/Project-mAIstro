---
inventory-delta:
  tests/: +21
---

# Issue #362 compliance registry gate

Adds twenty-one root tests covering registry schema validation, explicit
statuses, immutable evidence requirements, release-digest fail-closed behavior,
disabled or stale evidence, evidence scope and GitHub artifact provenance,
test-reference shape, and malformed or drifting COMPLIANCE.md table rows.
