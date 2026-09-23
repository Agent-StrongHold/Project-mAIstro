---
id: ADR-092326-97c4
title: "Shared PostgreSQL is the single owner of canonical Workspace identity"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-23
accepted: 2026-09-23
history:
  - status: Proposed
    date: 2026-09-23
  - status: Accepted
    date: 2026-09-23
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_workspace_authority_durable.py
  - packages/hive-conductor/backend/tests/test_workspace_authority.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-092326-97c4: Shared PostgreSQL is the single owner of canonical Workspace identity

## Context

Issue #37 requires exactly one canonical Workspace identity and store on
production paths. `maistro.workspaces` has durable PostgreSQL and SQLite stores
(#516, migration 019), and maistro-server serves them at `/v1/workspaces`
(#523). The shipped `docker-compose.yml` still ran more than one authority:

- The `hive-conductor` service got no `DATABASE_URL` or `DB_*`. Its embedded
  `MaistroCoreBridge` built a Container with no database, so the Container's
  `workspace_store` was an `InMemoryWorkspaceStore`.
- Because that store did not survive a restart, Hive wrote a recovery mirror
  into its own `stores.workspaces` on every mutation and replayed it on start.
  That mirror was the only durable record of Hive Workspaces and memberships.
- The canonical store changed first and the mirror second. If a mirror write
  failed, the acknowledged change and the durable record diverged. After a
  restart, a revoked member or a deleted Workspace came back.

Three options were considered. In the first, Hive calls maistro-server
`/v1/workspaces` as a remote authority. In the second, Hive keeps its own
durable store and maistro-server becomes secondary. The owner chose the third on
2026-09-23 (issue #37): both processes share one database.

## Decision

1. **One table, one owner.** In the shipped stack, Hive's embedded runtime uses
   maistro-engine's PostgreSQL. Its Container's `workspace_store` is the same
   `canonical_workspaces` / `canonical_workspace_memberships` pair that
   maistro-server serves. The `hive-conductor` compose service gets the same
   `DATABASE_URL` and `DB_*` as `maistro-engine`.
2. **Hive never migrates.** Hive depends on `postgres` being healthy and on
   `maistro-engine` being healthy. The engine's entrypoint runs
   `alembic upgrade head` under an advisory lock before it serves, so a healthy
   engine means a migrated schema. Container construction already refuses an
   unmigrated database.
3. **The mirror stops being an authority on the durable path.** Once the
   canonical store is durable, Hive stops writing to `stores.workspaces` on
   create, membership change, or delete, and stops replaying it on restart.
   Each legacy mirror row is imported into the canonical store once, keeping
   its id, members, roles, and timestamps. A `complete` entry in Hive's
   convergence journal is what makes the import idempotent. After the import,
   the canonical store's state wins. A Workspace or membership deleted or
   revoked there, whether through Hive or through maistro-server, is never
   brought back from the mirror. The mirror row itself is left as it is.
4. **Fail closed.** If a database is configured but the Container that holds
   the canonical store did not start, Workspace authorization refuses. It does
   not fall back to an in-process store rebuilt from the frozen mirror.
5. **Dev path unchanged.** With no database configured, Hive keeps using an
   in-process canonical store with the mirror as restart recovery evidence.

## Consequences

### Positive
- Workspaces created in Hive and in maistro-server live in the same rows, so
  Hive and `/v1/workspaces` see the same identity and membership.
- Revocations and deletions survive restarts. The divergence window between
  the canonical store and the mirror is gone on the shipped path.

### Negative / Trade-offs
- The journal that makes the import idempotent lives in Hive's local state. If
  that state is lost while the mirror rows survive, the next start imports the
  surviving rows again. That could bring back a Workspace deleted from the
  shared database after the first import.
- If the canonical database is replaced, mirror rows already marked imported
  are not re-imported. The shared database is the authority, and restoring it
  is an operator task.
- Hive now fails closed on Workspace authorization when its bridge cannot
  start against the configured database. Before, it continued on an ephemeral
  store.

### Neutral
- These remain open under #37 and are out of scope here: the Turing backend's
  private per-process `InMemoryWorkspaceStore`; maistro-server's
  `WorkspaceRoutingAdmitter` minting Root Projects for Workspace ids that have
  no `canonical_workspaces` row; and the missing
  `canonical_projects -> canonical_workspaces` foreign key.
