---
inventory-delta:
  packages/hive-conductor/backend/tests: 1
---

# #358 — canonical audit detail authorization

Adds one convergence test using the real Container/SQLite audit binding and
Hive authentication. A dual-written gate decision naming the requesting user
must not become readable through its legacy detail ID when the canonical
list/export authority is admin-only (ADR-073). The same response is required
for absent IDs, and a forbidden lookup proves authorization precedes replica
I/O. Existing legacy detail tests retain personal-scope/admin behavior.

Validation and regression evidence: `docs/testing/358-4c1c8-repair.md`.
