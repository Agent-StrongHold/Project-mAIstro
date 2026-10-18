---
inventory-delta:
  packages/maistro-core/tests: +29
---
# p0-8-store-boundary-scope

Workspace cutover P0.8 (#364): `tests/workspaces/test_store_boundary_scope_conformance.py`
asks the four stores the Workspace consumes (workspaces, projects, runs, audit)
whether a principal outside a record's scope can read or mutate it by id, plus
whether a Run's `actor_principal_id` is required and non-blank at admission and
whether audit rows carry and filter by `org_id`. Cases that do not hold today are
entries in the module's strict `KNOWN_GAPS` set, asserting the unscoped behaviour.

+29 is the count without a PostgreSQL server: 13 cases on each of memory and
SQLite, plus 3 backend-independent checks. The PostgreSQL leg (13 more) is
collected only when `MAISTRO_TEST_PG_DSN` or `MAISTRO_REQUIRE_PG_LEGS` is set,
which the inventory job does not set, so it does not move this number.
