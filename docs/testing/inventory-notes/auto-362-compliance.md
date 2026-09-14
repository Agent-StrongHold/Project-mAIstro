---
inventory-delta:
  tests/: +16
---

# Issue #362 compliance registry gate

Adds sixteen root tests covering registry schema validation, explicit statuses,
immutable evidence requirements, release-digest fail-closed behavior, disabled
or stale evidence, and malformed or drifting COMPLIANCE.md table rows.
