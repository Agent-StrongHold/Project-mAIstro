---
inventory-delta:
  tests/: +32
---
# m2-325-table-inventory

`tests/test_check_durable_table_inventory.py` is new: 32 tests for
`scripts/check-durable-table-inventory.py`, the gate that holds
`quality/durable-table-retention.json` to the tree (#325). Eleven cover
discovery (single-line, multi-line, constant-named and keyword
`op.create_table`; raw `CREATE [UNLOGGED] TABLE [IF NOT EXISTS]` in migrations
and runtime DDL; docstrings and temp tables ignored; `__tablename__`). Twenty
cover the gate itself (missing, stale and duplicate entries; an unresolvable,
non-callable or unqualified deletion path; a driven retention with no path;
`undecided` with no issue; a missing or malformed parent; bad enum values; a
malformed entry or inventory; discovery failure reported rather than raised;
`security_violations` or `usage_events` removed) and its exit codes. One runs
the gate against the real repository. Nothing was moved or removed.
