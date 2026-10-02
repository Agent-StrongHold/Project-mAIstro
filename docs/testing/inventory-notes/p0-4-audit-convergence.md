---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---
# p0-4-audit-convergence

Workspace cutover P0.4 (one durable audit store), tests only. Five cases drive
real Hive paths with a SQLite Container bound where the bridge binds it: failed
login, elevation, HITL cancel, denied chat tool call, and `GET /v1/audit`.
Every case is in `KNOWN_GAPS` (#53 / #325) because Hive's `log_audit` still
writes `stores.audit_log` and nothing reads the core Sentinel `AuditLog`.
