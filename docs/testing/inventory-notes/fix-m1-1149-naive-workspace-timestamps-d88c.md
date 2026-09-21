---
inventory-delta:
  packages/maistro-core/tests: +10
---
# fix-m1-1149-naive-workspace-timestamps-d88c

Ten new tests for #1149, all parametrized over two non-UTC `TZ` settings
(America/New_York, Pacific/Kiritimati) to prove the fix is host-independent:

- `test_timestamps.py` (new file, 6 cases): a naive `Workspace`/
  `WorkspaceMembership` timestamp normalizes to UTC identically under both
  zones; an already-aware timestamp is left alone.
- `test_workspace_import_identity_durable.py` (4 new cases): the "convergence
  import" path (`create(..., created_at=...)`) normalizes a naive
  `created_at` to UTC identically under both zones, for both the SQLite and
  PostgreSQL backends.

No tests removed or renamed.
