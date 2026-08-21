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

See `blakematthews-dev/project_maistro` specs/infra/S-140-sqlite-singleton.md for full spec.

## Acceptance Criteria

- [ ] Conductor process opens exactly one SQLite write-mode connection across its lifetime
- [ ] `open_writer()` raises if called more than once; `open_reader()` returns read-only connections
- [ ] CI gate fails the build if any production code opens SQLite in non-`ro` mode outside the singleton module
- [ ] All subsystem writes route through `state.submit(transaction)`
- [ ] Queue is bounded; overflow applies backpressure (submit blocks) rather than dropping or OOMing
- [ ] Concurrent reads from many subsystems + Console + external `sqlite3` CLI work without contention while the writer is active
- [ ] WAL checkpoint runs periodically; database file does not grow unboundedly
- [ ] State database backups are encrypted with the admin keypair (SPEC-011-style age encryption) before writing to disk; no plaintext copy of `state.db` is ever written to `~/.conductor/backups/`; backup files use the `.db.age` suffix and are importable via `maistro db restore`
- [ ] Schema migrations run atomically at startup; a failed migration rolls back completely and conductor refuses to start with a `MIGRATION_FAILED` error naming the failing migration; conductor never starts with a partially-migrated schema
