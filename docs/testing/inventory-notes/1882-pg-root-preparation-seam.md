---
inventory-delta:
  packages/maistro-core/tests: +7
---
# 1882-pg-root-preparation-seam

Issue #1882: prepare validated PG root Runs before transaction acquisition.

`PgRunStore` already split Run creation at its only seam (#1940's
`prepare_run`/`insert_prepared_run`), but the split had no root-only public
face and no direct tests: every proof of the ordering — scope-store I/O
finished before the admission connection is acquired — was indirect, through
`create_run` or through the tasks-side coordinator tests. This change adds the
root-only seam the issue names (`prepare_root_run`: scope validation, actor
requirement, graph copy, `admit_in_state`, parentless by construction), routes
the parentless branch of `create_run` and `prepare_run` through it, and adds
seven maistro-core node IDs in a new module,
`packages/maistro-core/tests/runs/test_pg_root_preparation.py`.

What the seven prove, on a real migrated PostgreSQL (they skip without
`MAISTRO_TEST_PG_DSN`, and `MAISTRO_REQUIRE_PG_LEGS` turns that skip into a
failure, because a skipped PG case is not durability proof):

- the prepared candidate carries exactly the validated semantics the
  canonical row later shows, including copies (not aliases) of the graph and
  provenance and the `admit_in_state` decision applied before any write;
- wrong scope (foreign-Workspace Project and missing Project), a blank or
  missing actor, and an unadmissible initial state all refuse with zero
  canonical rows written;
- on a dedicated `max_size=1` pool whose single connection is the Project
  store's only route, preparation completes, leaves the pool with no
  connection still checked out and no canonical row, and the subsequent
  transaction acquisition plus `insert_prepared_run` succeeds — the ordering
  the seam exists to guarantee;
- preparation deliberately invoked while the caller holds that same
  connection (the mis-ordered caller of #1845's joint commit) cannot complete
  within a deterministic guard timeout, and completes immediately once the
  connection is released — the timeout is a deadlock guard, not a latency
  bound, and a scratch run confirmed it fails when the scope read is
  bypassed, so the guard is not vacuous;
- the child path is unchanged: the pairing guard, the shared child-scope
  check, missing parents and a legitimate prepared child all behave as the
  spine suite already pins them across memory, SQLite and PostgreSQL.

No existing node IDs were removed or renamed; the spine conformance suite
(408 nodes with this module in its invocation) passes unchanged.
