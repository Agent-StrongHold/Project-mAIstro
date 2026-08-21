---
id: SPEC-070226-fbe3
title: "Deployment topology, backup, and disaster recovery"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-07-02
substrate:
  - maistro-engine#ADR-081
  - maistro-engine#ADR-087
  - maistro-engine#SPEC-230
implements:
  - maistro-engine#ADR-081
related:
  - maistro-engine#ADR-077
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-fbe3: Deployment topology, backup, and disaster recovery

## Context

Hive Conductor currently runs on localhost for development. ADR-081 specifies production deployment
topology: multi-instance high-availability (active-active or active-passive), persistent state
backup, and recovery procedures for data loss / instance failure.

## Goals

- Multi-instance deployment (horizontal scale, failover).
- Persistent state backup (PostgreSQL, Redis, file storage).
- Disaster recovery procedure (restore from backup, verified).
- Monitoring and alerting for degradation.

## Non-goals

- Multi-region failover (Stronghold).
- Zero-downtime upgrades (Phase 2).

## Decision

### Deployment architecture

```
load-balancer (nginx/haproxy)
├── maistro-server instance 1 (stateless)
├── maistro-server instance 2 (stateless)
└── maistro-server instance N

Persistent layer (outside instances):
├── PostgreSQL primary + replication follower (streaming replication, failover via etcd)
├── Redis (HA via Sentinel or Cluster)
└── File store (S3 or local NFS)
```

### Backup strategy

- **PostgreSQL**: daily full backup + continuous WAL archival.
- **Redis**: RDB snapshot to S3 daily; AOF on each instance.
- **Files**: nightly rsync to backup NFS or S3.
- **Configuration**: version-controlled in Git (separate private repo or encrypted).

### Failover and recovery

- **Primary PostgreSQL fails**: Sentinel/etcd promotes replica automatically (< 1s downtime).
- **Instance fails**: load balancer removes it; no data loss (state is in PostgreSQL/Redis).
- **Data corruption**: restore from backup (point-in-time recovery using WAL + RDB).
- **Full disaster**: restore PostgreSQL from backup, Redis from snapshot, reboot all instances.

### Verification

- Automated restore-and-verify test weekly: restore backup to staging, run smoke tests, confirm
  no data loss.

## Implementation status (2026-07-02)

Engine-side artifacts are landed; live-infrastructure validation (replication lag,
chaos/failover tests, alerting wiring) happens at deploy time on real infrastructure:

- Runbook: `docs/install/deployment-topology.md` (topology, backup, recovery
  procedures, weekly drill).
- Reference artifacts: `deploy/docker-compose.prod.yml` (nginx LB + 2 stateless
  replicas + PostgreSQL primary/streaming replica + Redis), `deploy/nginx.conf`,
  `deploy/init-replication.sh`, `deploy/scripts/backup.sh`,
  `deploy/scripts/verify-restore.sh`.
- Health endpoints for the LB already exist in maistro-server
  (`/health`, `/health/live`, `/health/ready` — `maistro_server/api/health.py`,
  tested in `tests/api/test_health.py`).

## Acceptance criteria

- [x] All persistent state (agents, sessions, memory, audit logs) is in PostgreSQL or Redis
      (no local files except config). *(Topology enforces this; instances are stateless.)*
- [ ] PostgreSQL replicas are catching up (replication lag < 1s). *(Live-infra check.)*
- [x] Backup test: restore yesterday's backup, verify data is present and consistent.
      *(`deploy/scripts/verify-restore.sh` — pg_dump hash + row-count check.)*
- [ ] Instance failure: one instance goes down, remaining handle traffic without data loss.
      *(Chaos test at deploy time; LB passive checks configured.)*
- [ ] Monitoring alerts on replication lag > 5s or backup failure. *(Wired at deploy time;
      queries/hooks documented in the runbook.)*

## Testing

- Chaos test: kill one instance, verify failover and no lost requests.
- Restore test: simulate data corruption, restore from backup, verify consistency.
- Property: "backup restore always produces bit-for-bit identical PostgreSQL state" (via pg_dump hash).

## References

- [ADR-081: Deployment Topology](../adr/ADR-081-deployment-backup-dr.md)
