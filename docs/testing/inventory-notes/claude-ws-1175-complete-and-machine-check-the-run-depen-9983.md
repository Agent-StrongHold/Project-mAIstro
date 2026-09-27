---
inventory-delta:
  packages/maistro-core/tests: +13
---
# claude-ws-1175-complete-and-machine-check-the-run-depen-9983

Eight maistro-core node IDs arrive with the Run purge dependent-reference
inventory check (#1175): `tests/runs/test_retention_reference_inventory.py`
scans the Alembic chains, `.sql` migrations, runtime DDL and ORM models for a
table with a `run_id` column and asserts each is named in `RUN_REFERENCING_TABLES`, plus
synthetic sources that must be reported (a written-out migration column, a
loop-built `add_column` over module constants, an ORM model and runtime DDL), a check that
the scan sees each discovery shape, that every inventoried table still exists,
and that every inventoried table has a policy row.

Five more node IDs arrive with a Codex review follow-up on the same PR,
closing three gaps in that scan: (1) a table a migration once gave `run_id`
and a later one drops entirely is now excluded via `gate.discover`'s own
create/drop replay, instead of being reported forever with no inventory state
that could pass both this test and the schema-existence one; (2) the scan now
resolves `run_id` reaching a runtime `ALTER TABLE` through a tuple-unpacking
loop or a `dict.items()` loop (the SQLite twins' idiom in `sqlite_outcomes.py`
et al.), and refuses -- rather than silently passing -- a formatted DDL
statement whose interpolated value it cannot resolve; (3) the "every
inventoried table has a policy row" check now parses the docstring's actual
table rows instead of a bare substring search, so a table named only in
surrounding prose no longer counts as having a policy. Nothing else moved.
