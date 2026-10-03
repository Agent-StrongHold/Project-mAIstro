# Production deployment topology, backup, and disaster recovery

Runbook for the production (multi-instance) profile of maistro-engine. Implements
[SPEC-070226-fbe3](../specs/SPEC-070226-fbe3-deployment-topology.md) and
[ADR-081](../adr/ADR-081-deployment-backup-dr.md). For single-host homelab sizing see
[sizing.md](./sizing.md); for the installer path see [default-installer.md](./default-installer.md).
Reference artifacts live in [`deploy/`](../../deploy/).

Per ADR-081 this document sets **no hard RPO/RTO or throughput numbers** — capacity is
measure-first, and the local backup is the required floor; everything off-host is an
optional connector.

---

## 1. Topology

**Storage policy.** [ADR-082226-5104](../adr/ADR-082226-5104-storage-architecture-postgres-durable-ladybug-working-memory.md) applies to laptop, team and enterprise
installs: PostgreSQL is the sole canonical durable application datastore. One cluster hosts
separate `maistro`, `litellm` and `langfuse` logical databases, each with separately owned
migrations. MAIstro uses core asyncpg + Alembic; no parallel PostgREST memory authority or
SQLite production twin is part of the target. Redis is operational queue/cache state, not a
second canonical owner. Existing alternate writers/data require verified, non-destructive
cutover; this runbook does not declare that retirement complete.

The root `docker-compose.yml` uses Langfuse v2 with PostgreSQL. Langfuse v3's additional
ClickHouse/Redis services belong to that optional topology, not the current root stack.
Backup/restore must cover each deployed application's logical database under its owner;
a MAIstro-only dump is not evidence that LiteLLM or Langfuse was restored.


```
load balancer (nginx, deploy/nginx.conf)
├── maistro-server replica 1 (stateless)
├── maistro-server replica 2 (stateless)
└── ... replica N

Persistent layer (outside instances):
├── PostgreSQL primary  ── streaming replication ──> hot-standby replica
│     (wal_level=replica, archive_mode=on → WAL archive volume)
├── Redis (AOF on-instance + daily RDB snapshot; Sentinel/Cluster for HA at scale)
└── File store (shared volume; S3 or NFS in real deployments)
```

- **Instances are stateless — except the task queue.** Agents, sessions, memory,
  audit and every canonical Run have PostgreSQL as their canonical durable owner; the only local files are
  config (in git) and the shared file store. **The `/v1/tasks` queue does not:**
  `TaskQueue` is an in-process singleton, so a task is visible only on the replica
  that accepted it. Behind round-robin, a client that creates a task and polls
  `GET /v1/tasks/{id}` gets 404 from every other replica — measured on this stack:
  200 from the replica that took the `POST`, 404 from the other. The task's Run
  *is* durable and shared; its queue entry is not. Until the queue is shared,
  route task traffic to one replica (or pin clients with `ip_hash`), and expect
  tasks in flight on a replica that dies to be lost with it.
- **Rate limits are per-process, not cluster-wide (#842).** The request limiter
  (`maistro_server.api.rate_limit`) keeps its sliding window in process memory,
  keyed to the authenticated principal (ADR-085). Each of the N replicas
  enforces `RATE_LIMIT_PER_MINUTE` independently, so the effective aggregate
  budget is N × the configured limit. A cluster-wide floor would need the
  shared store (e.g. the Redis above); none is claimed today.
- **Health gating.** The LB routes only to replicas passing `/health/ready`
  (nginx passive checks + compose healthchecks). `/health/live` is the unconditional
  liveness probe (ADR-038). `stop_grace_period: 30s` gives replicas a connection-drain
  window on rolling updates.
- **SIGTERM semantics (#819).** Uvicorn owns SIGTERM/SIGINT for the server
  process: on receipt it stops accepting connections and runs the lifespan
  shutdown, which drains in-flight tasks for up to `SHUTDOWN_DRAIN_TIMEOUT`
  (30s, `maistro_server/main.py`) — tasks still running when that window
  closes are cancelled and marked FAILED — then tears down MAIstro-owned
  sandbox containers, closes shared outbound clients, flushes the usage log
  and disposes the DB engine before the process exits. A signal-driven stop
  exits with the conventional "died of SIGTERM" status (Uvicorn re-raises the
  captured signal after shutdown completes), which is what orchestrators
  expect. Size `stop_grace_period` to cover the drain window **plus** that
  teardown — a deployment whose tasks legitimately run longer than 30s must
  raise the grace period (or the tasks keep getting cancelled at the drain
  deadline), and SIGKILL must remain only the runaway backstop, never the
  normal path.
- **Reference stack:** `deploy/docker-compose.prod.yml` (LB + 2 replicas +
  primary/replica PostgreSQL + Redis). Stronghold-scale deployments map the same
  shape onto Kubernetes + Helm (ADR-081).
- **Failover automation:** the compose reference uses a manually promoted replica
  (§4.1). Deployments needing sub-second automated failover add Patroni/etcd (Postgres)
  and Redis Sentinel; the runbook steps below are the manual equivalent.

Bring it up:

```bash
cp deploy/.env.example deploy/.env   # then set every change-me, LITELLM_BASE_URL and LITELLM_API_KEY
docker compose -f deploy/docker-compose.prod.yml up -d
curl -fsS http://localhost:8080/lb-health
curl -fsS http://localhost:8080/health/ready
```

The `.env` goes in `deploy/`, beside the compose file, because that is where
Compose looks: with `-f deploy/docker-compose.prod.yml` the project directory is
`deploy/`, not the directory you run the command from. These steps used to say
`cp deploy/.env.example .env`, which leaves every variable unread and fails the
second command with `required variable POSTGRES_PASSWORD is missing a value`.

---

## 2. Backup strategy

| What | How | Cadence |
|---|---|---|
| PostgreSQL | `pg_dump -Fc` full dump + continuous WAL archival (`archive_command`) | daily full, WAL continuous |
| Redis | `SAVE` → copy `dump.rdb` off-volume; AOF enabled on each instance | daily |
| Files | copy/rsync of the file-store volume | nightly |
| Config | version-controlled in git; backup records the deployed ref | on change |

[`deploy/scripts/backup.sh`](../../deploy/scripts/backup.sh) handles **one selected PostgreSQL
database per invocation**, plus the reference stack's Redis/files/config snapshot. Its public
selector is `POSTGRES_DB` (default `maistro`), with `POSTGRES_USER` selecting an existing
authorized backup role; internal `PG_DB`/`PG_USER` shell variables are not configuration inputs.
A default run is not a backup of LiteLLM or Langfuse. Each application owner must include its
deployed database and verify its restore separately. The script writes
`${BACKUP_ROOT}/YYYY-MM-DD/postgres-${POSTGRES_DB}.dump`, a plain SQL dump and its SHA-256.

For the reference production Compose topology, repeat the existing script per deployed
database, with a separate `BACKUP_ROOT` to isolate database artifacts and retention. The
following is an operator template, not an executed backup receipt. `BACKUP_ROLE` must already
be authorized for all listed databases; otherwise invoke each database separately with its
owner's existing role. Both loops stop on the first failed database rather than letting a
later success hide it. Do not create grants or expose credentials as part of this procedure.

```bash
# Use only databases actually deployed; use their actual names if customized.
for db in maistro litellm langfuse; do
  POSTGRES_DB="$db" POSTGRES_USER="${BACKUP_ROLE:?set an authorized role}" \
    BACKUP_ROOT="/var/backups/maistro/$db" \
    bash deploy/scripts/backup.sh || exit "$?"
done
```

The script defaults to `deploy/docker-compose.prod.yml`/`postgres-primary`; it also assumes
the reference `deploy_wal-archive`, `deploy_redis-data` and file-store volumes. It is **not**
a drop-in root-Compose/Langfuse-v3 backup command. Use this template only where those
reference services/volumes exist; other topologies need an owner-verified procedure before
claiming backup coverage. Repeating it also repeats shared Redis/file snapshots. Optional
off-host shipping remains deployment-specific (`REMOTE_TARGET` placeholders must be completed);
the script does not implement an off-host transfer merely by setting the variable.

Monitoring: alert on backup-script failure (non-zero exit / missing today's directory)
and on replication lag > 5s:

```sql
-- on the primary
SELECT client_addr, write_lag, replay_lag FROM pg_stat_replication;
```

---

## 3. Weekly restore-and-verify drill

Run [`deploy/scripts/verify-restore.sh`](../../deploy/scripts/verify-restore.sh) weekly
for **each** database backed up in §2, using its matching `POSTGRES_DB`, `POSTGRES_USER`,
`BACKUP_ROOT` and backup date. `PG_IMAGE` must match the source PostgreSQL major version and
required extensions; its default is `pgvector/pgvector:pg17`. It restores only to its uniquely
named scratch container and removes that container on exit, never into the running application.

```bash
# BACKUP_DATE is an existing YYYY-MM-DD directory under each database's root.
for db in maistro litellm langfuse; do
  POSTGRES_DB="$db" POSTGRES_USER="${BACKUP_ROLE:?set the matching role}" \
    BACKUP_ROOT="/var/backups/maistro/$db" \
    PG_IMAGE="${RESTORE_PG_IMAGE:?set the matching version/extensions image}" \
    bash deploy/scripts/verify-restore.sh "${BACKUP_DATE:?set backup date}" || exit "$?"
done
```

Record each database's dump path/date, script exit and restore result; one `maistro` PASS
cannot discharge the other owners' requirements. These are parameterized invocations supported
by the scripts, not evidence that a restore has been performed. The script:

1. Takes the selected date's dump (yesterday by default) and restores it into a throwaway
   scratch PostgreSQL container.
2. Re-runs `pg_dump` on the restored DB and compares its SHA-256 to the hash recorded
   at backup time — the spec's property: *backup restore always produces bit-for-bit
   identical state (via pg_dump hash)*.
3. Prints per-table row counts and fails if zero user tables were restored.
4. Does **not** run application-level smoke tests. Before declaring application recovery proven,
   each owner separately restores into an isolated staging environment and checks its own
   application/version/migration compatibility and representative reads. For MAIstro include
   `GET /health/ready` and a smoke request; LiteLLM and Langfuse require their own owner checks.
   The script's scratch container is already cleaned up on exit, so it cannot serve that step.

A failing drill is a paging alert: your backups are not restorable.

---

## 4. Recovery procedures

### 4.1 Primary PostgreSQL fails — promote the replica

1. Confirm the primary is dead (do NOT promote while it may still take writes):
   ```bash
   docker compose -f deploy/docker-compose.prod.yml exec postgres-primary pg_isready || echo "primary down"
   ```
2. Check the replica is current (replayed the latest WAL it received):
   ```bash
   docker compose -f deploy/docker-compose.prod.yml exec postgres-replica \
     psql -U maistro -c "SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();"
   ```
3. Promote:
   ```bash
   docker compose -f deploy/docker-compose.prod.yml exec postgres-replica \
     psql -U maistro -c "SELECT pg_promote();"
   ```
4. Repoint **every deployed client of the shared cluster**, not only MAIstro. Promotion does
   not move the failed `postgres-primary` hostname. For the two `maistro-server-*` services,
   set `DB_HOST=postgres-replica` in their configuration and recreate them with
   `docker compose ... up -d maistro-server-1 maistro-server-2`. If Hive embeds a Container,
   its owner updates the same canonical database endpoint too. LiteLLM and Langfuse owners
   update their own PostgreSQL connection endpoint to the promoted host, keeping each
   logical database, role and migration ownership unchanged, and restart/reload their clients
   using the deployed version's procedure. Do not copy one application's credentials into
   another or change grants to complete failover.
   A stable failover endpoint can avoid per-client host edits only if **all** clients already
   use it and its owner has verified that it routes to the newly writable primary; merely
   deploying Patroni/pgbouncer does not prove this. Inventory and record each client endpoint.
5. Verify each application's actual connection and representative read/write against the
   promoted database through its owner. MAIstro includes
   `curl -fsS http://localhost:8080/health/ready`; Hive, LiteLLM and Langfuse require their own
   version-appropriate health/application checks. A passing MAIstro health check alone is not
   shared-cluster recovery evidence. Do not declare recovery complete while any deployed
   client still targets the failed primary.
6. Rebuild a new standby from the promoted node before considering the incident closed:
   wipe the old primary volume, then re-run its container with the `pg_basebackup -R`
   bootstrap pattern (see the `postgres-replica` command in `docker-compose.prod.yml`)
   pointed at the new primary.

### 4.2 App-instance failure

Canonical durable data remains in PostgreSQL; Redis owns only its operational state. nginx ejects the failing
replica (`max_fails=3 fail_timeout=10s`); `restart: unless-stopped` brings it back.
To replace manually: `docker compose -f deploy/docker-compose.prod.yml up -d --force-recreate maistro-server-1`.

### 4.3 Data corruption — point-in-time restore (PITR)

1. Stop writes to each database being restored. For MAIstro: `docker compose -f deploy/docker-compose.prod.yml stop maistro-server-1 maistro-server-2`. LiteLLM/Langfuse owners stop their own writers before their database restore; stopping MAIstro alone is insufficient.
2. Preserve the corrupted data directory (copy the `pgdata-primary` volume aside for forensics).
3. Select the database owner, matching dump date and destination explicitly. For the per-database
   roots in §2, the logical dump is `/var/backups/maistro/<DB>/<DATE>/postgres-<DB>.dump`;
   legacy single-database backups may still use the old root, so verify the actual path.
   Logical restore loses changes after the dump; WAL cannot be replayed onto a logical dump.
   MAIstro example (each other application owner repeats with its own database, role and dump):
   ```bash
   pg_restore -U maistro -d maistro --clean --if-exists --no-owner \
     /var/backups/maistro/maistro/<DATE>/postgres-maistro.dump
   ```
   PITR requires an independently captured compatible physical `pg_basebackup` base and
   its matching cluster WAL; `backup.sh` does not create that physical base. Do not claim
   PITR readiness from its logical dumps alone. Restore the verified physical base, then create
   `recovery.signal` and set in `postgresql.conf`:
   ```
   restore_command = 'cp <VERIFIED_MATCHING_WAL_ARCHIVE>/%f %p'
   recovery_target_time = '<timestamp just before corruption>'
   ```
   Start postgres; it replays WAL to the target, then pauses for promotion
   (`SELECT pg_wal_replay_resume();` / `pg_promote()`).
4. Each owner verifies its restored database and application state. The §3 script tests a
   separate scratch restore of the selected dump, not this operational destination; for PITR,
   validate the intended recovery point rather than expecting equality with an earlier dump.
5. Restart each restored application only after its owner checks pass. For MAIstro restart
   its replicas and check `/health/ready`; LiteLLM/Langfuse use their own version/migration and
   representative-read checks. Preserve their separate migration ownership.

### 4.4 Full disaster — rebuild from scratch

1. Provision a host with Docker; clone the repo (config is in git — ADR-081) at the
   ref recorded in `deployed-git-ref.txt` inside the backup.
2. Recreate `.env` from the secrets manifest (age-encrypted, `vault.py` — ADR-081).
3. Start only the persistent layer:
   ```bash
   docker compose -f deploy/docker-compose.prod.yml up -d postgres-primary redis
   ```
4. Restore **each deployed logical database** through its application owner using its matching
   `/var/backups/maistro/<DB>/<DATE>/postgres-<DB>.dump` (§4.3). A restored `maistro` database
   alone does not recover LiteLLM or Langfuse. Physical cluster recovery instead requires the
   separately verified base/WAL procedure described there.
5. Choose the matching reference-stack shared snapshot (with the §2 layout, under
   `/var/backups/maistro/maistro/<DATE>/`). Restore Redis: stop redis, copy `redis-dump.rdb` into the
   `redis-data` volume as `/data/dump.rdb`, start redis.
6. Restore the file store from that same shared snapshot's `files/` into the `file-store` volume.
7. Start the standby, replicas, and LB:
   ```bash
   docker compose -f deploy/docker-compose.prod.yml up -d
   ```
8. Verify MAIstro readiness (`curl -fsS http://localhost:8080/health/ready`) and replication
   (`pg_stat_replication`); each other deployed application owner verifies its own restored
   state. Run §3 separately for each saved dump as the scratch-restore drill, not as evidence
   that all running application databases were restored.
