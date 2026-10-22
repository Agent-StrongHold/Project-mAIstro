---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
---

# #358: recovered audit router preserves the authenticated page contract

Repaired the existing degraded-mode recovery test; no collected cases added or
removed. It previously required anonymous HTTP 200 from the audit router and
failed with 401. Now it mounts the production AuthMiddleware, rejects anonymous
reads, uses a real administrator login session, and reads the bounded page
containing the actual optional-router degradation event. It checks the envelope,
page limit, system actor, target, and warning severity rather than accepting a
status-only response. No authorization bypass or production code change.

Fail-first evidence and executed validation: `docs/testing/358-08fa-repair.md`.
