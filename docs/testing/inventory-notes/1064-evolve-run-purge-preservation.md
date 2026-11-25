---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Evolve domain records survive execution retention (#1064)

The existing core `test_every_run_id_table_is_in_the_purge_inventory` failed
at the assigned head: migration 069's `evolve_domain_publications` and
`evolve_domain_snapshots` lacked a declared Run purge policy. Register both
as **preserve under Run purge**, consistent with producer attribution
(ADR-083026-e602) and canonical checkpoint ownership (ADR-083026-6e2a).
Snapshots reconstruct the Workspace's Evolve domain for later cycles; journal
keys prevent duplicate effects. Neither authorizes execution or resurrects a
purged Run. Their independent compaction/expiry policy remains undecided in
the existing durable-table ledger; this repair does not claim a driven sweep.

`test_evolve_domain_retention.py` adds two behavioral legs (SQLite, PostgreSQL):
persist a real terminal canonical Run/NodeRun/Attempt with an expired deadline,
write Evolve snapshot/battle/finalize records attributing that Run, actually
purge the Run, and verify the domain records survive unchanged. A duplicate
battle still loses its fence while a new logical NodeRun can publish. SQLite
uses the same database file for spine and domain, so preservation is not an
artifact of isolated databases. PostgreSQL uses the migrated production tables.

Regression evidence: before the inventory fix, the existing core contract test
fails with exactly the two Evolve table names (captured in job baseline log).
No quality ledgers or grant files changed: the CI-exact vulture scan already
passes with 1221 reviewed findings and zero unclassified identities.

Validation in this repair round:

- `uv run pytest packages/maistro-core/tests/runs -x -q` with PostgreSQL:
  2061 passed, 4 skipped (six pre-existing aiosqlite teardown warnings).
- `uv run pytest packages/maistro-evolve/tests -x -q`: 1005 passed, 12 skipped.
- `uv run pytest packages/hive-conductor/backend/tests/test_evolution*.py
  packages/hive-conductor/backend/tests/test_evolve_domain*.py -x -q` with
  PostgreSQL: 140 passed, including both new retention legs.
- `uv run pytest tests/cross_product_parity/test_cross_product_parity.py -x -q`:
  26 passed. Ruff check/format, cross-package imports, durable-table inventory
  (126 tables), Hive suite inventory (4424 identities), exact vulture gate pass.

Run PostgreSQL suites sequentially: the core fixture truncates canonical
scratch tables, so running it concurrently with Hive replay tests can remove
an in-flight Run. The isolated Hive rerun passed without code changes.

This repairs the evidenced purge-inventory gap, not the entire issue's
close-only proof: fresh-pool Run replay is not an actual process kill, and
faulted/in-progress finalization remains an explicit refusal rather than
transparent resume at every boundary. Exact-head remote CI and #947 review
disposition are unverified here. No issue closure or integration approval.
