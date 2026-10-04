---
id: SPEC-010
title: "SQLite singleton writer — the invariant that protects state under the reactor"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-018
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-010: SQLite Singleton Writer

## Bounded storage scope — 2026-10-03

The target role of SQLite is the small bootstrap/configuration state permitted by
[ADR-082226-5104](../adr/ADR-082226-5104-storage-architecture-postgres-durable-ladybug-working-memory.md). It is not a universal domain-state writer: canonical Runs,
Workspace identity, memory and other durable domain records belong to PostgreSQL core stores
with Alembic-owned migrations. Explicit test and historical import tools are outside this
production singleton boundary. **Until verified migration and retirement, all currently
live production SQLite writers remain subject to this singleton/acknowledgement, backpressure,
checkpoint and atomic-upgrade contract**, including transitional domain families such as
accounts, sessions, profiles, registration policy and layouts in the
[Conductor persistence map](../architecture/CONDUCTOR-PERSISTENCE-MAP.md). Reclassifying a
family as “not bootstrap” does not release its guard or permit a second writer. Existing data
must be preserved; this transitional protection does not authorize new SQLite canonical
features or claim that the PostgreSQL cutover is complete.

See `blakematthews-dev/project_maistro` specs/infra/S-140-sqlite-singleton.md for full spec.

## Acceptance Criteria

- [ ] When production SQLite state is enabled, its Conductor owner opens exactly one write-mode connection across its lifetime, covering bootstrap/configuration and all still-live transitional domain writers
- [ ] `open_writer()` raises if called more than once; `open_reader()` returns read-only connections
- [ ] CI gate fails the build if any production SQLite writer opens in non-`ro` mode outside the singleton module; transitional domain writers remain covered until their verified migration and retirement
- [ ] All current production SQLite subsystem writes route through `state.submit(transaction)`; canonical PostgreSQL writes use their own core stores, not this singleton
- [ ] Queue is bounded; overflow applies backpressure (submit blocks) rather than dropping or OOMing
- [ ] Concurrent reads from many subsystems + Console + external `sqlite3` CLI work without contention while the writer is active
- [ ] WAL checkpoint runs periodically; database file does not grow unboundedly
- [ ] State database backups are encrypted with the admin keypair (SPEC-011-style age encryption) before writing to disk; no plaintext copy of `state.db` is ever written to `~/.conductor/backups/`; backup files use the `.db.age` suffix and are importable via `maistro db restore`
- [ ] Existing production SQLite schema migrations (including transitional domain data) run atomically at startup; a failed migration rolls back completely and conductor refuses to start with a `MIGRATION_FAILED` error naming the failing migration; conductor never starts with a partially-migrated schema
