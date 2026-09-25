---
inventory-delta:
  packages/maistro-core/tests: +6
---
# claude-ws-1175-complete-and-machine-check-the-run-depen-9983

Six maistro-core node IDs arrive with the Run purge dependent-reference
inventory check (#1175): `tests/runs/test_retention_reference_inventory.py`
scans the Alembic chains, `.sql` migrations and runtime DDL for tables with a
`run_id` column and asserts each is named in `RUN_REFERENCING_TABLES`, plus
synthetic migration and runtime-DDL sources that must be reported, a check that
the scan sees each discovery shape, that every inventoried table still exists,
and that every inventoried table has a policy row. Nothing else moved.
