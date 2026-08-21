---
id: SPEC-213
title: "First Alembic migration: memory tables + pgvector extension"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-20
substrate:
  - maistro-engine#ADR-011
  - maistro-engine#ADR-012
implements:
  - maistro-engine#ADR-012
related:
  - maistro-engine#SPEC-212
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-213: First Alembic migration: memory tables + pgvector extension

## Context

The SQLAlchemy models defined in `memory/store.py` (`TaskRecord`, `MemoryEntry`,
`KnowledgeNode`) plus the T2 memory types (`Learning`, `EpisodicMemory`,
`Outcome`) had no Alembic migration, so they could not be created via
`alembic upgrade head` against a fresh Postgres. ADR-012 decided to add a
single initial migration covering all six tables and to wire `Base` into
`alembic/env.py` so future autogeneration works.

## Goals

- One Alembic migration that creates all six T0–T2 memory tables.
- Pre-create the `vector` Postgres extension (required by `MemoryEntry`'s
  pgvector column) before the table that depends on it.
- `alembic/env.py` imports `Base` from `memory.store` so `--autogenerate`
  produces correct diffs for future migrations.

## Non-goals

- Zero-downtime/online migration strategies.
- Production index tuning (left to deployment-specific follow-up).

## Decision

`alembic/versions/001_initial_memory_schema.py` creates, in order:

1. `CREATE EXTENSION IF NOT EXISTS vector` (idempotent — gracefully no-ops if
   pgvector isn't installed-but-already-present, or if run twice).
2. `tasks` (`TaskRecord`)
3. `memory_entries` (`MemoryEntry`, includes the `vector` column — depends on
   step 1)
4. `knowledge_nodes` (`KnowledgeNode`)
5. `learnings` (`Learning`)
6. `episodic_memories` (`EpisodicMemory`)
7. `outcomes` (`Outcome`)

`downgrade()` drops in reverse order; the T2 tables (`learnings`,
`episodic_memories`, `outcomes`) can be dropped independently via a future
migration without touching the T0 tables since each `op.drop_table` call is
scoped to its own table.

`alembic/env.py` imports `Base` from `maistro.memory.store` (or the
equivalent module path) so `alembic revision --autogenerate` diffs against
the live model metadata rather than a stale snapshot.

## Acceptance criteria

- [x] `alembic/versions/001_initial_memory_schema.py` exists and creates all
      6 tables
- [x] pgvector extension is created before `memory_entries`
- [x] `alembic/env.py` imports `Base` for autogenerate support
- [ ] `alembic downgrade -1` from head drops only the T2 tables, leaving T0
      tables intact (not independently re-verified in this pass — inherited
      from ADR-012's acceptance criteria, recommend confirming with a real
      Postgres run before relying on it in production)

## Testing

No dedicated migration test suite exists; verification is via running
`alembic upgrade head` / `alembic downgrade -1` against a live Postgres
instance (manual or CI integration step), not unit tests.

## Open questions

- Whether to add an `alembic check`-style CI gate that fails on model/migration
  drift (ADR-012 listed this as an acceptance criterion but no such CI step
  currently exists).

## References

- [ADR-011: Memory engine + session factory wiring](../adr/ADR-011-memory-engine.md)
- [ADR-012: First Alembic migration (memory tables + pgvector)](../adr/ADR-012-alembic-migration.md)
- [SPEC-212: Memory engine + async session factory wiring](SPEC-212-memory-engine-session-wiring.md)
- `alembic/versions/001_initial_memory_schema.py`
- `alembic/env.py`
