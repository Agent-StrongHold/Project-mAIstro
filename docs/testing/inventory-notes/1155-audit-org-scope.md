---
inventory-delta:
  packages/maistro-core/tests: +19
---
# 1155 audit organization scope

The audit persistence change adds nineteen regression tests: PostgreSQL
SQL/write and real two-organization migration/isolation coverage, SQLite
legacy-schema upgrade/index and two-organization isolation coverage, explicit
system-scope and ambiguous-scope checks, unsupported-filter rejection, a
canonical Sentinel-to-SQLite durable write, canonical audit-entry identity,
and the in-memory audit filter. Existing tests were adjusted for the persisted
column, exact system-scope predicate, and parameter positions.
