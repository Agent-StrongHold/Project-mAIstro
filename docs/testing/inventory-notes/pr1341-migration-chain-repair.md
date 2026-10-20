---
inventory-delta:
  tests/: +2
---
# PR 1341 migration-chain repair

Added two metadata checks that detect duplicate Alembic revision IDs and
multiple migration heads before database-backed migration tests run. Renamed
the newly merged HITL deadline migration from revision `033` to `034` (with
`033` as its predecessor), preserving a single linear chain after the existing
project-membership migration also uses `033`.
