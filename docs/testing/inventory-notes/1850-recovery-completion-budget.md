---
inventory-delta:
  packages/maistro-core/tests: +28
---
# Count persisted recovery progress (#1850)

Adds nine cases across the existing memory, SQLite and PostgreSQL spine
fixture (27 collected nodes; PostgreSQL remains skipped without its test DSN)
and one file-backed SQLite close/reopen proof. Core collection moves from
12,079 to 12,107. No tests are removed or weakened.

The accepted-prefix regression requires the later completion on the first
limit=1 tick and unchanged physical evidence on repeat. Companions cover
parent-only settlement, bounded page traversal past an unchanged RUNNING
Run, peer acceptance/settlement interleavings followed by an unchanged tick,
read failures before/after reconciliation, and missing progress records.
The close/reopen proof recovers the persisted two-node residue through a
fresh Container and verifies unchanged Attempt evidence and idempotence.
The existing one-tick crash-window oracles remain unchanged.
