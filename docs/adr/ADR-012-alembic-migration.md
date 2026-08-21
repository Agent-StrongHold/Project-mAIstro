---
id: ADR-012
title: First Alembic migration (memory tables + pgvector)
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-011
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-012: First Alembic migration (memory tables + pgvector)

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T2  
**Depends on:** ADR-011

---

## Context

The three SQLAlchemy models in `memory/store.py` have no corresponding Alembic migration. They cannot be created via `alembic upgrade head`.

Additionally, new tables are added in T2 (`learnings`, `episodic_memories`, `outcomes`) that need their own migration.

## Decision

Update `alembic/env.py` to import `Base` from `memory.store` so auto-generation works. Create `alembic/versions/001_initial_memory_schema.py` covering all T0–T2 tables:

- `tasks` (existing `TaskRecord`)
- `memory_entries` (existing `MemoryEntry`)
- `knowledge_nodes` (existing `KnowledgeNode`)
- `learnings` (new — `Learning` persistence, T2)
- `episodic_memories` (new — `EpisodicMemory` persistence, T2)
- `outcomes` (new — `Outcome` persistence, T2)

Migration creates the `vector` extension if not exists before creating `memory_entries` (requires pgvector).

## Acceptance criteria

- [ ] `alembic upgrade head` against a fresh Postgres creates all 6 tables
- [ ] `alembic downgrade -1` drops the T2 tables without touching T0 tables
- [ ] `alembic check` passes (no drift between models and migration)
- [ ] pgvector extension pre-creation handled gracefully

## Out of scope

Online migration strategies (zero-downtime). Column-level indices for production tuning.

## Source references

- `./alembic/env.py` (existing — update)
- `./alembic/versions/` (add 001 migration)
