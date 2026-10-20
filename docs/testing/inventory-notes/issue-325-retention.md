---
inventory-delta:
  packages/maistro-core/tests: +7
  packages/maistro-turing/backend/tests: +1
---
# Issue 325 retention: bounded purge mechanisms for the durable tables

Every number below is a collected node ID against the prior recorded
inventory for its suite.

`packages/maistro-core/tests` (+7):

- `tests/quota/test_sqlite_usage_log.py` (+3): the durable raw→aggregate
  boundary — `purge_expired` upserts UTC-day sums into
  `usage_event_aggregates` before deleting the same bounded batch in one
  transaction (exact expiry boundary: the cutoff row survives), legal hold is
  scope-isolated (`legal_hold_scopes` skips held scopes' rows entirely), and
  repeated bounded purges aggregate exactly the deleted batch, so survivors
  of a bounded sweep are never re-aggregated and double-counted.
- `tests/events/test_durable_log.py` (+2): the sqlite canonical event log's
  `purge_expired` is bounded and honors `legal_hold_entity_ids` (the durable
  sqlite/pg envelope purges; in-memory legs skip the case).
- `tests/persistence/test_sqlite_audit.py` (+1): the audit log's
  `purge_expired` respects the expiry boundary and the explicit
  `legal_hold_user_ids` hold set.
- `tests/workspaces/test_store_boundary_scope_conformance.py` (+1): the
  append-only boundary suite's own scoped admission case for `purge_expired`
  — selection is strictly cutoff-timestamp, never by id, and the hold wins
  over expiry; the allowlist entry must not become license for a by-id
  delete.

`packages/maistro-turing/backend/tests` (+1): the Turing bounded window is
per-Workspace — a user's turn evicts only that user's terminal Runs (and
reclaims the evicted Run's graph continuation first); the pre-scoping
process-global window deleted another user's Run the moment the process-wide
window overflowed.

Not counted here, on purpose:

- `tests/` (root): the branch's parallel inventory-checker tests
  (`test_check_retention_inventory.py`, +3) were removed in the develop sync
  — trunk's CI-wired `scripts/check-durable-table-inventory.py` (backed by
  `quality/durable-table-retention.json`, replaying migrations and checking
  `deletion_path` importability, with its own root test) is the one
  machine-checked inventory for #325, so the duplicate gate and its tests
  were retired rather than merged alongside it. Net root delta: 0.
- Run-retention spine tests are unchanged from trunk (`m2-1175.md` records
  those); the resolved merge kept trunk's reviewed versions of
  `test_retention_policy.py`, `test_retention_conformance.py`,
  `test_retention_scope_conformance.py`, and `test_wiring.py` verbatim.
