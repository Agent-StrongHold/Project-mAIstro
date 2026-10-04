# Durable State Contract

## Canonical policy and current wiring

[ADR-082226-5104](../adr/ADR-082226-5104-storage-architecture-postgres-durable-ladybug-working-memory.md) makes PostgreSQL the sole canonical durable production
backend, including laptops and homelabs. MAIstro uses core asyncpg stores and Alembic;
LiteLLM/Langfuse own separate logical databases and migrations on the same cluster.
SQLite is permitted for small bootstrap/configuration state, explicit tests and necessary
historical import/readers. New canonical stores do not need SQLite twins or schema parity.

The matrix below describes **current implementation**, not additional supported production
backends or completed retirement. `AgentConfig.database_url` still selects PostgreSQL or
file-backed SQLite stores; `memory://`, an empty URL, and pathless `sqlite://` are
process-local profiles and log what is lost on restart. Unsupported database URLs fail at
startup rather than falling back to memory. Existing SQLite data and its integrity guarantees
must survive a verified migration before alternate production writers are retired. SQLite
fixture success is not proof of PostgreSQL crash/restart, concurrency or replica safety.

The enforcement and accounting families have these dispositions:

| Family | Current relational wiring (SQLite is transitional/test) | Ephemeral profile |
| --- | --- | --- |
| audit | `PgAuditLog` / `SqliteAuditLog` | `InMemoryAuditLog` |
| elevation grants | relational `ElevationStore` | `InMemoryElevationStore` |
| sessions | `PgSessionStore` / `SqliteSessionStore` | `InMemorySessionStore` |
| strikes | `PgStrikeTracker` / explicit disabled state | `InMemoryStrikeTracker` |
| quota totals | `PgQuotaTracker` / `SqliteQuotaTracker` | `InMemoryQuotaTracker` |
| learnings | PostgreSQL or SQLite learning store | `InMemoryLearningStore` |
| rate-window events | PostgreSQL is currently memory-only; SQLite uses `SqliteUsageLog` | `InMemoryUsageLog` |

SQLite rate-window events remain synchronous in memory for hot-path decisions.
`SqliteUsageLog` restores them at startup and uses stable event identities plus
a unique database constraint so overlapping flushes and crash/retry cannot count
one logical provider call twice. A response boundary or shutdown owner must call
`Container.flush_usage_log()`; health reports this write-behind requirement.

`/health/ready` exposes `persistence` diagnostics for each family. The
`durable` value describes the store actually wired, not merely the configured
Foundation/State flag, and does not include credentials or grant proofs.
Short-lived OAuth state, replay records, skill registries, identity lifecycle
stores, and local resilience policy defaults remain process-local by design;
they are not restart-survival contracts and are reported as such by their
owning subsystem rather than being mistaken for durable enforcement state.
