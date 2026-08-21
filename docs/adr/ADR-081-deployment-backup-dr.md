---
id: ADR-081
title: "Deployment Topology, Backup, and Disaster Recovery"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-056
  - maistro-engine#ADR-026
  - maistro-engine#ADR-071
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# ADR-081: Deployment Topology, Backup, and Disaster Recovery

**Status:** Proposed
**Date:** 2026-05-30
**Substrate:** ADR-038 (reliability taxonomy, health/readiness probes, error budgets).

---

## Context

The engine ships in two shapes that have never been reconciled into one operational contract.
Agent Conductor is the homelab/personal product — a handful of users, tens of concurrent tasks,
sometimes a local P40 image-gen box — and wants to run on a single host with no orchestration
overhead. Stronghold (ADR-019, planned) imports the engine, adds multi-tenancy, and needs to scale
horizontally. Two profiles, but they share one runtime, so they must share one set of operational
guarantees: the same health/readiness/startup probes (ADR-038), the same drain-on-shutdown
behavior, and the same backup/export story. Without an ADR, each deployment reinvents probes and
backup ad hoc, and "how do I get my data out" has no answer.

A second gap: there is no documented backup baseline and no portable export format. Operators cannot
recover from a lost disk, and users cannot move their settings/agents/DAGs between this tool and
others. We do not want to over-commit to cloud infrastructure (the homelab profile may have none),
so the contract must hold with nothing but local disk.

## Decision

Two parts, one ADR.

### (A) Deployment — two profiles, shared contract

| | Agent Conductor (homelab) | Stronghold (horizontal) |
|---|---|---|
| Packaging | `docker-compose` on a single host | Kubernetes + Helm |
| Scale | a few users, tens of concurrent tasks | horizontal, many replicas |
| Image-gen | optional local P40 | external/managed |
| Probes | ADR-038 health/readiness/startup | ADR-038 health/readiness/startup |
| Rollout | rolling update + connection drain | rolling update + connection drain |

Both profiles **wire the ADR-038 probes** (liveness/health, readiness, startup) and a
**rolling-update + connection-drain** strategy: a replica leaving service stops accepting new work,
drains in-flight tasks to a deadline, then exits.

**Capacity is measure-first.** This ADR sets **no hard numeric throughput targets**. Concurrency
caps are established **empirically** per deployment, and the system relies on **backpressure via the
ADR-071 reconciler** rather than a guessed ceiling — when the reconciler reports the system is behind
its desired state, admission slows. Numbers come from measurement, not from this document.

### (B) Backup + disaster recovery

- **Local backup is the required baseline.** Every deployment can produce a self-contained local
  backup (DB dump + secrets manifest + config) on disk with no external dependency. This is the
  floor; nothing else is mandatory.
- **Cloud-backup connectors are OPTIONAL and pluggable.** Operators may enable one or more of
  Google Drive, Azure, S3, Backblaze to ship the local backup off-host. **None is required** beyond
  the local backup, and no specific provider is assumed.
- **Portable structured exports.** Independent of backup, the engine emits human-portable exports:
  **settings as JSON/YAML**, and **agents / DAGs / dashboards as JSON**. These double as a
  **cross-platform import path** — the same JSON shape is what you import from another tool — so the
  export format is also an ingest format.

**No fixed RPO/RTO is mandated.** The contract is the *shape* — local backup (required) + optional
cloud connectors + portable exports — not a recovery-time number. Deployments that need a specific
RPO/RTO schedule the cloud connector cadence themselves.

### Backup contract (shape, not schema)

```text
backup (local, required)
  ├── database dump
  ├── secrets manifest (age-encrypted; vault.py)
  └── config snapshot
cloud connector (optional, pluggable: gdrive | azure | s3 | backblaze)
  └── ships the local backup off-host
exports (portable, structured)
  ├── settings        → JSON / YAML
  ├── agents          → JSON   ┐
  ├── dags            → JSON   ├─ also the cross-platform IMPORT path
  └── dashboards      → JSON   ┘
```

## Acceptance criteria

- [ ] Agent Conductor deploys via `docker-compose` on a single host; Stronghold deploys via
      Kubernetes + Helm — both from the same runtime.
- [ ] Both profiles expose the ADR-038 health, readiness, and startup probes.
- [ ] Both profiles perform a rolling update with connection drain: a departing replica stops
      admitting work, drains in-flight tasks to a deadline, then exits.
- [ ] No hard numeric throughput target is set; concurrency caps are configured empirically and the
      ADR-071 reconciler provides backpressure under load.
- [ ] A local backup (DB dump + encrypted secrets manifest + config) can be produced with no external
      dependency.
- [ ] At least one cloud connector (gdrive | azure | s3 | backblaze) can be enabled, and the system
      runs correctly with **none** enabled.
- [ ] Settings export to JSON/YAML; agents, DAGs, and dashboards export to JSON.
- [ ] The exported JSON for agents/DAGs/dashboards round-trips as an import — exporting then importing
      reconstructs the object.
- [ ] No RPO/RTO number is asserted as a contract; the local+optional-cloud+export shape is.

## Consequences

- One operational contract covers both products; probes and drain behavior stop being reinvented per
  deployment.
- Measure-first + ADR-071 backpressure means the system degrades gracefully under load instead of
  failing a guessed capacity assertion.
- The local-backup floor guarantees recoverability even on an offline homelab host; cloud connectors
  are pure opt-in upside.
- The export format being the import format gives users a real exit path and a real on-ramp from
  other tools, at the cost of keeping the JSON shape stable across versions.

## Out of scope

- The on-disk/wire schema of the backup artifact and the export JSON (follow-up SPEC).
- Specific RPO/RTO targets and cloud-connector cadence (operator configuration).
- Multi-region / cross-cluster failover topology — Stronghold (ADR-019).
- Secret rotation and key custody beyond the existing `vault.py` age encryption.
