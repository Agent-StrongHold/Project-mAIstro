---
inventory-delta:
  packages/maistro-core/tests: +11
  packages/hive-conductor/backend/tests: +2
---
# #65 canonical discovery repair

Adds three-backend conformance cases for bounded Workspace Goal and recent Run
discovery: filtering before pagination, deterministic ordering, invalid bounds,
detached values, and reopened Goal storage. PostgreSQL legs require a real server;
skips are not passing evidence. Scoped Goal discovery (+3) and
Run discovery (+2) assert member access and identical foreign/missing/blank
refusals. Product HTTP regressions (+2) prove zero-Run Goal intent and canonical-only
multi-Run history/backlinks, plus deduplication when a projection arrives.

Regression evidence: before production discovery changes, both new HTTP tests
failed with empty Goal lists. Before owner changes, the Goal conformance test
failed because InMemoryGoalStore had no list_goals method.

Validation: all 11 owner/scoping cases pass with a real migrated PostgreSQL 18
server as well as memory/SQLite (no skipped legs). Full core Goal/Run directories:
1,318 passed, 315 environment-gated skips. Full Conductor backend after fixing
its existing named-SVG role regression: 3,757 passed, 19 skipped. Both suite
inventory checks pass (core 16,520; Conductor backend 3,776). Existing canonical
Run inspection test now asserts discoverability instead of the retired
projection-only limitation; its count is unchanged. No new browser tests.

