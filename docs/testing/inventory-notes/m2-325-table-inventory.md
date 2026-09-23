---
inventory-delta:
  tests/: +29
---
# m2-325-table-inventory

`tests/test_check_durable_table_inventory.py` is new: 29 tests for
`scripts/check-durable-table-inventory.py`, the gate that holds
`quality/durable-table-retention.json` to the tree (#325). Ten cover discovery
(single-line, multi-line, constant-named and keyword `op.create_table`; raw
`CREATE TABLE [IF NOT EXISTS]` in migrations and runtime DDL; docstrings and
temp tables ignored; `__tablename__`). Eighteen cover the gate itself
(missing, stale and duplicate entries; an unresolvable deletion path; a driven
retention with no path; `undecided` with no issue; an uninventoried parent;
bad enum values; a malformed entry or inventory; a non-callable or unqualified
path; `security_violations` or `usage_events` removed) and its exit codes. One
runs the gate against the real repository. Nothing was moved or removed.
