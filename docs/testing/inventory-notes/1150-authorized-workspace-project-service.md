---
inventory-delta:
  packages/maistro-core/tests: +6
---
# Issue 1150 authorization service inventory

Adds two service-boundary tests (six collected parametrized nodes) covering cross-Workspace reads/mutations and EffectiveAuthorization-based Project delegation over in-memory, SQLite, and configured PostgreSQL backends. The PostgreSQL leg skips unless `MAISTRO_TEST_PG_DSN` is configured and becomes required when `MAISTRO_REQUIRE_PG_LEGS` is set.
