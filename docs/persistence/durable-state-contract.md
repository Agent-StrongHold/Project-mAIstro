# Durable State Contract

The container selects state from one canonical `AgentConfig.database_url` backend.
A `postgresql://` or file-backed `sqlite:///...` URL is durable; `memory://`, an
empty URL, and pathless `sqlite://` are explicit process-local profiles and log
what is lost on restart. Unsupported database URLs fail at startup rather than
falling back to memory.

The enforcement and accounting families have these dispositions:

| Family | Relational profile | Ephemeral profile |
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
