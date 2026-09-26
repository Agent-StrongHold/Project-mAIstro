---
inventory-delta:
  packages/maistro-core/tests: +8
---
# claude-ws-1175-complete-and-machine-check-the-run-depen-9983

Eight maistro-core node IDs arrive with the Run purge dependent-reference
inventory check (#1175): `tests/runs/test_retention_reference_inventory.py`
scans the Alembic chains, `.sql` migrations, runtime DDL and ORM models for a
table with a `run_id` column and asserts each is named in `RUN_REFERENCING_TABLES`, plus
synthetic sources that must be reported (a written-out migration column, a
loop-built `add_column` over module constants, an ORM model and runtime DDL), a check that
the scan sees each discovery shape, that every inventoried table still exists,
and that every inventoried table has a policy row. Nothing else moved.
