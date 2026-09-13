---
inventory-delta:
  packages/maistro-core/tests: +10
---
# 1155 audit organization scope

The audit persistence change adds ten regression tests: PostgreSQL SQL/write and
read reconstruction assertions, SQLite legacy-schema upgrade/index coverage,
two-organization isolation and filter-composition coverage, explicit ambiguous
scope rejection, and the in-memory audit filter. Existing tests were adjusted
only for the new persisted column and parameter position.
