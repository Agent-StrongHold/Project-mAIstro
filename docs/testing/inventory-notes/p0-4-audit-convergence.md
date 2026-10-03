---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# p0-4-audit-convergence

Workspace cutover P0.4 (one durable audit store), tests only. Six tests: five
cases drive real Hive paths with a SQLite Container bound where the bridge binds
it (failed login, elevation, HITL cancel, denied chat tool call, and
`GET /v1/audit`), plus a guard that every `KNOWN_GAPS` entry names a real case.
Every case is in `KNOWN_GAPS` (#53 / #325) because Hive's `log_audit` still
writes `stores.audit_log` and nothing reads the core Sentinel `AuditLog`.
Post-convergence assertions expect Hive's current actor key (username for auth
and HITL cancel, `user_id` for chat-tool blocks). `@pytest.mark.ac` for
SPEC-100126-c041/AC-4 waits until #1768 lands.
