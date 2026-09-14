---
inventory-delta:
  tests/: +15
---

# Issue #362 compliance registry gate

Adds fifteen root tests covering registry schema validation, explicit statuses,
immutable evidence requirements, release-digest fail-closed behavior, and
malformed or drifting COMPLIANCE.md table rows.
