---
inventory-delta:
  packages/maistro-core/tests: +15
---
# 1155 audit organization scope

The audit persistence change adds fourteen regression tests: PostgreSQL
SQL/write and SQLite legacy-schema upgrade/index coverage, two-organization
isolation and filter-composition coverage, explicit system-scope and ambiguous
scope checks, a canonical Sentinel-to-SQLite durable write, and the in-memory
audit filter. Existing tests were adjusted for the persisted column, exact
system-scope predicate, and parameter positions.
