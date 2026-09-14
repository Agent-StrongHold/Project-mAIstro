---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---

# Issue #289: OpenAI-compatible credential lifecycle

Adds backend API tests covering the generic OpenAI-compatible provider catalog,
credential-write authorization, non-persisting connectivity/model discovery
probe, encrypted-key create and rotation, metadata-only edit, disable, delete,
and config-only cleanup lifecycle. The probe uses a transport seam, so the test
never needs a live gateway or credential.
