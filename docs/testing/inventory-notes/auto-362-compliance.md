---
inventory-delta:
  tests/: +26
---

# Issue #362 compliance registry gate

Adds root tests covering registry schema validation, explicit statuses,
immutable evidence requirements, release-digest fail-closed behavior, disabled
or stale evidence, evidence scope and GitHub artifact provenance, test-reference
shape, release-required unverified controls, the no-tag evidence workflow, and
malformed or drifting COMPLIANCE.md table rows.
