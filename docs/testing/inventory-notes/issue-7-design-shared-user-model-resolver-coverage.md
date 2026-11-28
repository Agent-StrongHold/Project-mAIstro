---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---

# Issue #7 row 18 / AC-15: the resolver's unavailability and composition paths are proven

CI's diff-coverage gate (per file, lines 90% / branches 80%) failed
`packages/hive-conductor/backend/services/user_model.py` at 64.1% of its 39
changed lines: the hive-conductor producer (the only producer that measures
that module) showed the resolver's two remaining degradation branches, its
composition success path, and the recall-outage path as never executed.

Four tests join `test_design_shared_surfaces.py`, all under the AC-15 marker
(`SPEC-091726-7c2a/AC-15`), each naming the line the gate named:

1. `test_resolver_refuses_to_compose_without_the_core_audit_log` — PostgreSQL
   configured, core runtime absent (no canonical audit log) → `None`, never a
   half-composed service (lines 82–84, 93).
2. `test_resolver_refuses_to_compose_without_the_design_session_factory` —
   audit present, design engine absent → `None` (lines 94–96, 105).
3. `test_resolver_composes_the_shared_service_over_postgres` — all seams
   present → the canonical `UserModelService` over `PostgresUserModelStore`
   bound to the design deployment's own session factory, audit log attached
   (lines 106–109).
4. `test_recall_failure_degrades_to_none` — a recall outage answers `None`
   (omitted context) and is logged, never raised through the chat surface
   (lines 145, 148, 149).

No production code changed; the tests drive the same public module surface
(`resolve_user_model_service`, `recall_for_design_task`) the six earlier
tests already exercise through `/v1/chat/stream`.
