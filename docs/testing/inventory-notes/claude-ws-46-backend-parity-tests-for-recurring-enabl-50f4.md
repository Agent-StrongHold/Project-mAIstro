---
inventory-delta:
  packages/maistro-core/tests: +6
---
# claude-ws-46-backend-parity-tests-for-recurring-enabl-50f4

Adds `packages/maistro-core/tests/scheduling/test_admission_backend_parity.py`
(#46): two scenarios, each parametrized over the memory, SQLite and PostgreSQL
backends, for +6 node IDs. The scenarios are recurring enable/disable/max_runs
through `ScheduleRunAdmitter` and a not-yet-due schedule's first `next_due_at`.
The PostgreSQL leg skips without `MAISTRO_TEST_PG_DSN`, but it is still
collected. No tests were removed or moved.
