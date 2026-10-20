---
inventory-delta:
  packages/maistro-core/tests: +7
---
# p0-5-effect-context-convergence

Workspace cutover P0.5 (backend-selected effect context), tests only. Seven
tests: memory/sqlite/postgres store-class selection (pass on develop after
#1321/#1760), plus three strict `KNOWN_GAPS` (#804): `default_effect_context()`
is not the Container's `capability_effects`, GovernedInvocation `_approvals`
is None on SQLite, and capability vs container `invocation_store` are two
durable instances. PostgreSQL leg skipped without `MAISTRO_TEST_PG_DSN`.
