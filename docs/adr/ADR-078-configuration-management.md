---
id: ADR-078
title: "Configuration Management — DB source of truth, RBAC online edit, file export"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate:
  - maistro-engine#ADR-068
implements: []
related:
  - maistro-engine#ADR-073
  - maistro-engine#ADR-031
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-078: Configuration Management — DB source of truth, RBAC online edit, file export

**Status:** Proposed
**Date:** 2026-05-30
**Defines the engine config model** that ADR-073 already assumes ("policy tunables live in the DB,
RBAC-gated online-editable, exported to human-readable form") but never specified centrally.

---

## Context

Config today is scattered: some lives in files, some in the DB, with no rule for which goes where or
how it is changed safely. Several subsystems need to change behavior **without a deploy** — Sentinel
thresholds, RLPHD weights, feature flags, the model registry and routing rules. Others must **not**
change at runtime because doing so would break the running process — the DB connection string, the
bootstrap parameters, the secrets. ADR-073 already presumes a config model with DB-backed,
RBAC-gated, online-editable tunables and human-readable export; this ADR makes that model canonical
and draws the line between hot-editable and static config.

## Decision

**The database is the online source of truth for nearly all configuration**, and that config is
**editable at runtime under RBAC** (ADR-068). A small, explicit set of config that would break the
process if edited live stays **static in files / Helm / Vault**.

### What lives in the DB (online, hot-editable, RBAC-gated)

Anything that is safe to change while the process runs:

- Sentinel policy and thresholds (the ADR-073 declarative layer).
- RLPHD parameter weights (`θ`).
- Feature flags.
- The model registry and routing rules.
- General tunables (timeouts, limits, budgets).

Each edit is authorized by RBAC and audited. (How a learned/declarative policy change is gated
against drift is ADR-073's concern; this ADR provides the store and the edit path.)

### What stays static in files (cannot be hot-edited)

Config whose live mutation would break the running system:

- **Deployment topology** — what runs where, ports, replica counts.
- **Bootstrap parameters** — including the DB connection itself.
- **Secrets** — held in Vault / sealed secrets, never in the DB config table.

### Precedence

A **static bootstrap file** is read first and provides exactly two things: the **DB connection** and
the **secrets** needed to reach it. Once the DB is reachable, **everything else is read from the DB**
(and written back to it on edit). The bootstrap file is the only config the process needs before it
can talk to the database; it cannot be edited online.

```
read order:
  1. bootstrap file  -> DB connection + secrets    (static, file/Helm/Vault, NOT hot-editable)
  2. DB config        -> everything else            (online source of truth, RBAC-edited at runtime)

  static file  ─wins for→  { db connection, secrets, topology }
  DB           ─wins for→  { sentinel policy, RLPHD θ, feature flags, model registry, tunables }
```

### Export for backup and history

The DB config is **exported to human-readable YAML/JSON** on a schedule and on change, so that:

- backups exist outside the database,
- changes appear in git history (auditable diffs of who changed which tunable),
- a future restore path can reload a known-good snapshot.

Export is a **derived artifact**, not an input: the DB remains authoritative, and the exported files
are read back only by an explicit restore, never silently on boot.

```python
class ConfigStore(Protocol):
    async def get(self, key: str) -> ConfigValue: ...
    async def set(self, key: str, value: ConfigValue, *, principal: Principal) -> None: ...  # RBAC + audit
    async def export(self) -> bytes: ...   # human-readable YAML/JSON snapshot for backup / git
```

## Acceptance criteria

- [ ] Sentinel policy/thresholds, RLPHD weights, feature flags, the model registry/routing rules, and
      general tunables are stored in the DB and are the online source of truth.
- [ ] A DB config edit takes effect at runtime without a deploy and is gated by RBAC (ADR-068) and
      audited (rejected for an unauthorized principal).
- [ ] Deployment topology, bootstrap parameters, and secrets stay in files / Helm / Vault and are not
      writable through the online config path.
- [ ] A static bootstrap file supplies the DB connection and secrets; all other config is read from
      the DB after the connection is established.
- [ ] DB config exports to human-readable YAML/JSON for backup and git history; the export is derived
      and is never read on boot except via an explicit restore.

## Consequences

- Operators change behavior (policy, flags, routing, tunables) live, under RBAC, without a deploy.
- The DB becomes the authoritative config plane; its availability is on the hot path for config reads
  (mitigated by caching and the static bootstrap fallback for connectivity).
- Config changes gain a git-visible audit trail via export, without making files the source of truth.
- The hot-editable / static split is explicit, so a class of "edited live and broke the process"
  failures (topology, secrets) is prevented by construction.

## Out of scope

- The drift/conformance gate on policy changes — ADR-073 (and its ADR-074 Rehearse gate) own that.
- The DB config table schema and the caching/invalidation strategy (a follow-up SPEC).
- Secret management mechanics (rotation, sealing) — handled by Vault; this ADR only excludes secrets
  from the DB config plane.
- Multi-tenant config partitioning — Stronghold (ADR-019).
