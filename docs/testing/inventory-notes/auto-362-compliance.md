---
inventory-delta:
  tests/: +19
---

# Issue #362 compliance registry gate

Adds nineteen root tests covering registry schema validation, explicit statuses,
immutable evidence requirements, release-digest fail-closed behavior, disabled
or stale evidence, GitHub artifact provenance, and malformed or drifting
COMPLIANCE.md table rows.
