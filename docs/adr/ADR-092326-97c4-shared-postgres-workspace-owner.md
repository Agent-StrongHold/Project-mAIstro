---
id: ADR-092326-97c4
title: "Shared PostgreSQL is the single owner of canonical Workspace identity"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-23
accepted: 2026-09-23
ac-modules:
  AC-1: '@flat/hive-conductor/services.workspace_authority'
  AC-2: '@flat/hive-conductor/services.workspace_authority'
  AC-3: '@flat/hive-conductor/services.workspace_authority'
  AC-4: '@flat/hive-conductor/services.workspace_authority'
  AC-5: '@flat/hive-conductor/services.workspace_authority'
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
4. **Fail closed.** Workspace authorization refuses when a database is
   configured but the Container that holds the canonical store is not running.
   That covers a bridge that failed to start. It also covers a bridge that was
   never started, which happens when `MAISTRO_ROUTER_API_KEY` is empty.
   `install.sh` always generates that key. Hive never falls back to an
   in-process store rebuilt from the frozen mirror.
5. **Dev path unchanged.** With no database configured, Hive keeps using an
   in-process canonical store with the mirror as restart recovery evidence.
   This also applies when the database is in-process (`memory://`, or
   `sqlite://` with no path), since it does not survive a restart either.

## Acceptance criteria

Each criterion is one numbered decision above, proven in
`packages/hive-conductor/backend/tests/test_workspace_authority_durable.py`.
The PostgreSQL legs run where `MAISTRO_TEST_PG_DSN` is set; their SQLite twins
run everywhere.

- [x] **AC-1** With a database configured, Hive's embedded Container's
  `workspace_store` is the durable canonical store Workspace authorization
  reads, and the shipped compose file gives `hive-conductor` the engine's own
  `DATABASE_URL`/`DB_*`.
- [x] **AC-2** Hive never migrates: it starts only after `postgres` and
  `maistro-engine` are healthy, and its compose service runs no `alembic`.
- [x] **AC-3** On the durable path the mirror is imported once and never
  written or replayed; revocations and deletions survive a restart, and a
  failed create rolls back without touching the mirror.
- [x] **AC-4** A configured database with no running Container fails
  Workspace authorization closed, and `/health/ready` reports the instance
  not ready (503) until the Container is up.
- [x] **AC-5** With no database, or an in-process one, the ephemeral canonical
  store still serves and the mirror stays restart recovery evidence.

## Consequences

### Positive
- Workspaces created in Hive and in maistro-server live in the same rows, with
  the same ids and memberships. Hive's authorization (`is_member`,
  `member_role`) reads those rows directly.
- Revocations and deletions survive restarts. The divergence window between
  the canonical store and the mirror is gone on the shipped path.

### Negative / Trade-offs
- Hive's Workspace *views* (list, get, member routes) still require a
  Hive-owned `WorkspacePresentation`. A Workspace created only through
  maistro-server authorizes in Hive but is not listed in Hive's UI until one
  exists.
- An import can be interrupted after its canonical `create`, leaving its
  journal entry at `importing`. The next start then replays that row's legacy
  roster. Any canonical revocation made in that window is lost, and so is a
  deletion, because a missing Workspace is created again. The roster copy
  holds a process-local lock only, so a concurrent revocation through
  maistro-server can also be overwritten while the copy runs.
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
- Hive's Container now puts all of its stores on the shared database, not only
  Workspaces. That includes Runs, schedules and events. The stores already
  support multiple writers: the production compose file runs two maistro-server
  replicas on one database. Hive's recovery loops claim only Runs whose
  `admission_source` is `hive_legacy_dag`.
- The PostgreSQL legs of the tests run only where `MAISTRO_TEST_PG_DSN` points
  at a migrated database. Their SQLite twins run everywhere.
- These remain open under #37 and are out of scope here: the Turing backend's
  private per-process `InMemoryWorkspaceStore`; maistro-server's
  `WorkspaceRoutingAdmitter` minting Root Projects for Workspace ids that have
  no `canonical_workspaces` row; and the missing
  `canonical_projects -> canonical_workspaces` foreign key.
