---
id: ADR-011
title: Memory engine + session factory wiring
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-002
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-011: Memory engine + session factory wiring

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T2  
**Depends on:** ADR-002

---

## Context

`memory/store.py` defines `TaskRecord`, `MemoryEntry`, and `KnowledgeNode` SQLAlchemy models, but no engine or session factory — they are completely unwired. Every task starts from zero context, and task results vanish on restart.

## Decision

Add `get_engine()` and `get_async_session_factory()` to `memory/store.py`, cached via `functools.lru_cache`. Wire engine creation into `main.lifespan` so the pool is created on startup and disposed on shutdown. Add `get_db_session()` as an async-generator FastAPI dependency.

Engine is only created when `DATABASE_URL` is set in settings. If unset (dev/test), engine returns `None` and all persistence calls are no-ops. Tests run without Postgres.

## Interface

```python
# memory/store.py additions
def get_engine() -> AsyncEngine | None: ...          # lru_cache'd
def get_async_session_factory() -> async_sessionmaker | None: ...  # lru_cache'd
async def get_db_session() -> AsyncGenerator[AsyncSession, None]: ...  # FastAPI dep
def reset_engine_cache() -> None: ...               # test helper, clears lru_cache
```

## Acceptance criteria

- [ ] `get_engine()` returns `None` when `DATABASE_URL` unset
- [ ] `get_engine()` returns an `AsyncEngine` when `DATABASE_URL` is set
- [ ] `get_engine()` is idempotent (same object returned on repeated calls)
- [ ] `reset_engine_cache()` clears the cache for test isolation
- [ ] `main.lifespan` creates engine on startup, disposes on shutdown
- [ ] `get_db_session()` yields a usable `AsyncSession`

## Test plan

| Test | Covers |
|---|---|
| `test_get_engine_no_url_returns_none` | no DB graceful |
| `test_get_engine_idempotent` | cache hit |
| `test_reset_engine_cache` | test isolation |

## Source references

- `./src/maistro/memory/store.py` (existing)
- `./src/maistro/config/settings.py` (`DatabaseSettings`)
