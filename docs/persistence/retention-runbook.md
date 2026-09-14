# Durable retention runbook

`retention-inventory.json` is the policy registry. A table is not considered
covered merely because it has a TTL comment: it must have an owner, data class,
growth estimate, deletion constraint, action, and restore/hold behavior. The
quality gate compares the registry with both Alembic `op.create_table` calls
and shipped runtime `CREATE TABLE IF NOT EXISTS` schemas.

## Sweep contract

Every destructive sweep follows the same contract:

1. Select only rows whose expiry is strictly before the cutoff (the cutoff row
   is retained), excluding legal-hold scopes or principals.
2. Select at most the configured batch size in stable key order.
3. Aggregate or archive evidence before deleting its raw rows, in one database
   transaction. A failed transaction is retried without a partial disposition.
4. Delete dependents before owners. Run-family deletion is Workspace-scoped and
   accounts for NodeRuns, Attempts, graph continuations, schedule cursors and
   retained provenance references.
5. Return deleted and retained counts. Operators expose those counts with the
   retention health metrics; a failed sweep is not reported as successful.

PostgreSQL replicas coordinate through database transactions and row/key
locking. SQLite replicas coordinate through `BEGIN IMMEDIATE` and the
filesystem database lock. A sweep may be retried after restart and a bounded
batch makes outage backlog drain without an unbounded lock hold.

## Quota and security

`usage_events` is raw reconciliation evidence, not the current enforcement
ledger. The SQLite usage sweeper upserts UTC-day rows into
`usage_event_aggregates` before deleting raw rows. The in-memory quota window
is shorter than the raw reconciliation horizon, so removing rows older than the
configured cutoff cannot change current quota state. `quota_usage` cycle totals
remain the longer-lived accounting record.

`security_violations` and `audit_log` are immutable evidence during their audit
horizon. Purge methods only remove old evidence, never the live security strike
summary or an active leased record, and accept an explicit hold set. A hold is
therefore supplied by the authorization/erasure coordinator to every replica;
it is not process-local state. Canonical event provenance is retained by Run
purges unless a separate, authorized lawful-erasure policy explicitly covers it.

## Backup, restore, and holds

Backups include raw rows, aggregates, policy metadata, and hold state. Restoring
a backup does not bypass the policy: the next bounded sweep re-evaluates the
same cutoff and is idempotent. A legal hold wins over expiry until released by
the authority that placed it. Release of a hold does not delete synchronously;
it makes rows eligible for the next observable sweep. Operators must record the
backup snapshot and hold set used for any privacy or audit deletion.
