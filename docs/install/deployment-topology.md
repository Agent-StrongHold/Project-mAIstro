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

- **Instances are stateless.** All persistent state (agents, sessions, memory, audit)
  lives in PostgreSQL/Redis; the only local files are config (in git) and the shared
  file store. Any replica can serve any request.
- **Health gating.** The LB routes only to replicas passing `/health/ready`
  (nginx passive checks + compose healthchecks). `/health/live` is the unconditional
  liveness probe (ADR-038). `stop_grace_period: 30s` gives replicas a connection-drain
  window on rolling updates.
- **Reference stack:** `deploy/docker-compose.prod.yml` (LB + 2 replicas +
  primary/replica PostgreSQL + Redis). Stronghold-scale deployments map the same
  shape onto Kubernetes + Helm (ADR-081).
- **Failover automation:** the compose reference uses a manually promoted replica
  (§4.1). Deployments needing sub-second automated failover add Patroni/etcd (Postgres)
  and Redis Sentinel; the runbook steps below are the manual equivalent.

Bring it up:

```bash
cp deploy/.env.example .env   # or export vars: POSTGRES_PASSWORD, REPLICATION_PASSWORD, REDIS_PASSWORD, API_KEYS
docker compose -f deploy/docker-compose.prod.yml up -d
curl -fsS http://localhost:8080/lb-health
curl -fsS http://localhost:8080/health/ready
```

---

## 2. Backup strategy

| What | How | Cadence |
|---|---|---|
| PostgreSQL | `pg_dump -Fc` full dump + continuous WAL archival (`archive_command`) | daily full, WAL continuous |
| Redis | `SAVE` → copy `dump.rdb` off-volume; AOF enabled on each instance | daily |
| Files | copy/rsync of the file-store volume | nightly |
| Config | version-controlled in git; backup records the deployed ref | on change |

All of this is one script: [`deploy/scripts/backup.sh`](../../deploy/scripts/backup.sh)
(cron it daily). It writes a self-contained backup under `${BACKUP_ROOT}/YYYY-MM-DD/`
including a plain-SQL dump + `sha256` used by the verify drill, and optionally ships
off-host (`REMOTE_TARGET` — rsync/S3/wal-g, per the ADR-081 pluggable-connector rule).

Monitoring: alert on backup-script failure (non-zero exit / missing today's directory)
and on replication lag > 5s:

```sql
-- on the primary
SELECT client_addr, write_lag, replay_lag FROM pg_stat_replication;
```

---

## 3. Weekly restore-and-verify drill

Run [`deploy/scripts/verify-restore.sh`](../../deploy/scripts/verify-restore.sh) weekly
(cron). It:

1. Takes yesterday's dump, restores it into a throwaway scratch PostgreSQL container.
2. Re-runs `pg_dump` on the restored DB and compares its SHA-256 to the hash recorded
   at backup time — the spec's property: *backup restore always produces bit-for-bit
   identical state (via pg_dump hash)*.
3. Prints per-table row counts and fails if zero user tables were restored.
4. (staging extension) Point a staging maistro-server at the scratch DB and check
   `GET /health/ready` + a smoke request.

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
4. Repoint the app: set `DB_HOST=postgres-replica` for both `maistro-server-*`
   services (env/.env) and `docker compose ... up -d maistro-server-1 maistro-server-2`.
   (With Patroni/pgbouncer this step is automatic.)
5. Verify: `curl -fsS http://localhost:8080/health/ready`.
6. Rebuild a new standby from the promoted node before considering the incident closed:
   wipe the old primary volume, then re-run its container with the `pg_basebackup -R`
   bootstrap pattern (see the `postgres-replica` command in `docker-compose.prod.yml`)
   pointed at the new primary.

### 4.2 App-instance failure

No action required for data: state is in PostgreSQL/Redis. nginx ejects the failing
replica (`max_fails=3 fail_timeout=10s`); `restart: unless-stopped` brings it back.
To replace manually: `docker compose -f deploy/docker-compose.prod.yml up -d --force-recreate maistro-server-1`.

### 4.3 Data corruption — point-in-time restore (PITR)

1. Stop writes: `docker compose -f deploy/docker-compose.prod.yml stop maistro-server-1 maistro-server-2`.
2. Preserve the corrupted data directory (copy the `pgdata-primary` volume aside for forensics).
3. Restore the last daily base into a fresh data directory. Simple path (logical, loses
   sub-day changes unless you replay WAL):
   ```bash
   pg_restore -U maistro -d maistro --clean --if-exists --no-owner \
     /var/backups/maistro/<DATE>/postgres-maistro.dump
   ```
   PITR path (physical): restore a `pg_basebackup` base, then create
   `recovery.signal` and set in `postgresql.conf`:
   ```
   restore_command = 'cp /var/backups/maistro/<DATE>/wal_archive/%f %p'
   recovery_target_time = '<timestamp just before corruption>'
   ```
   Start postgres; it replays WAL to the target, then pauses for promotion
   (`SELECT pg_wal_replay_resume();` / `pg_promote()`).
4. Run the §3 verify steps (pg_dump hash + row counts) against the restored DB.
5. Restart the app replicas and check `/health/ready`.

### 4.4 Full disaster — rebuild from scratch

1. Provision a host with Docker; clone the repo (config is in git — ADR-081) at the
   ref recorded in `deployed-git-ref.txt` inside the backup.
2. Recreate `.env` from the secrets manifest (age-encrypted, `vault.py` — ADR-081).
3. Start only the persistent layer:
   ```bash
   docker compose -f deploy/docker-compose.prod.yml up -d postgres-primary redis
   ```
4. Restore PostgreSQL from the latest backup (§4.3 step 3).
5. Restore Redis: stop redis, copy `redis-dump.rdb` from the backup into the
   `redis-data` volume as `/data/dump.rdb`, start redis.
6. Restore the file store: copy the backup's `files/` into the `file-store` volume.
7. Start the standby, replicas, and LB:
   ```bash
   docker compose -f deploy/docker-compose.prod.yml up -d
   ```
8. Verify: `curl -fsS http://localhost:8080/health/ready`, replication catching up
   (`pg_stat_replication`), and run the §3 drill against the restored state.
