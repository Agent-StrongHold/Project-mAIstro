---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# Issue 358 repair — unmatchable-severity coverage + flat single-seek plan

## Why the count moved

`test_audit_convergence.py` gains
`test_unmatchable_severity_returns_an_empty_page_without_querying`: core's
AuditLog has no `critical` severity, so `page_core_audit_entries` must answer
an unmatchable `severity` filter with an empty page before the authority is
queried (`audit_bridge.py:185-186`). The arc was previously uncovered, which
is exactly what the quality diff-coverage gate failed on
(`audit_bridge.py: 75.0% of 4 changed branch arcs (need 80%); partial at 185`,
quality run 37891030162). The new test pins the contract behaviorally: empty
page for `/v1/audit?severity=critical`, empty NDJSON export, and a poisoned
`get_page` that fails the test if the foreign value ever reaches the
authority.

`_page_sql` (services/audit_query.py) also now emits a single-seek page flat
instead of wrapping one ordered seek in a UNION co-routine: on SQLite 3.45/3.46
the wrapper forced `USE TEMP B-TREE FOR ORDER BY` over the already-ordered
page, which failed
`test_million_row_corpus_pages_in_bounded_time`'s plan assertion on CI (run
37891030215, `packages/hive-conductor/backend/tests/test_audit_pagination.py:782`).
The million-row test's structural block now asserts the flat, sort-free plan
for both single-seek shapes (operator page via `idx_audit_log_order`, scoped
page via `idx_audit_log_actor`); no test node was added or removed there.

## Evidence

- `packages/hive-conductor/backend/tests`: 3,630 -> 3,631 collected (+1).
- Full backend suite: 3,612 passed, 19 skipped (3611 + the new test).
- Plan check of the exact production SQL on SQLite 3.46.1 (the reproducing
  version): every single-seek shape sorts free; sorts remain only inside the
  bounded multi-seek merges.
