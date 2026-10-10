---
inventory-delta:
  tests/: 2
---
# #358: preserve develop's planner revision when merging audit indexes

Two service-independent migration tests pin all eight audit index definitions
and their reverse-only downgrade. They independently assert scope-first indexes,
every equality-filter subset, stable timestamp/id ordering, and the 058 -> 057
revision edge. Before the repair the named 058 migration does not exist and
Alembic reports two 057 heads.

The existing chain test now checks both migration filenames/parents and the
single 058 head. The live audit rollback test starts and ends at 057 and checks
that its Run-store queue index survives. The admission rollback keeps the
captured original stamp assertion. These edits add no further collected tests.

No incoming develop migration or gate is weakened. PostgreSQL execution requires
a test database and remains explicitly unverified when skipped.
See `docs/testing/358-c203-repair.md` for executed validation and blockers.
