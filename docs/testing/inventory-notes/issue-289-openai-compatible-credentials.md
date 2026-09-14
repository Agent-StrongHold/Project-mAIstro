---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# Issue #289: OpenAI-compatible credential lifecycle

Adds backend API tests covering the generic OpenAI-compatible provider catalog,
credential-write authorization, non-persisting connectivity/model discovery
probe, encrypted-key create and rotation, metadata-only edit, disable, and
delete lifecycle. The probe uses a transport seam, so the test never needs a
live gateway or credential.
