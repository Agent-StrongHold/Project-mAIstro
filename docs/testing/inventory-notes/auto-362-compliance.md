---
inventory-delta:
  tests/: +20
---

# Issue #362 compliance registry gate

Adds twenty root tests covering registry schema validation, explicit statuses,
immutable evidence requirements, release-digest fail-closed behavior, disabled
or stale evidence, GitHub artifact provenance, test-reference shape, and
malformed or drifting COMPLIANCE.md table rows.
