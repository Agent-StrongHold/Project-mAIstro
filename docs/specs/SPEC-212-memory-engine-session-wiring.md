---
id: SPEC-212
title: "Memory engine + async session factory wiring (lazy, cached, DB-optional)"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-20
substrate:
  - maistro-engine#ADR-002
  - maistro-engine#ADR-011
implements:
  - maistro-engine#ADR-011
related:
  - maistro-engine#SPEC-213
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-212: Memory engine + async session factory wiring (lazy, cached, DB-optional)

## Context

`memory/store.py` defines the SQLAlchemy models (`TaskRecord`, `MemoryEntry`,
`KnowledgeNode`) but, prior to ADR-011, had no engine or session factory —
they were unwired, so every task started from zero context and results
vanished on restart. ADR-011 decided to add cached engine/session-factory
accessors and wire engine lifecycle into the app's startup/shutdown, while
keeping persistence fully optional so tests run without Postgres.

## Goals

- Provide a single, cached `AsyncEngine` and `async_sessionmaker` for the
  whole process, created only when `DATABASE_URL` is configured.
- Wire engine creation/disposal into the FastAPI app lifespan.
- Provide a `get_db_session()` async-generator FastAPI dependency.
- Allow tests to reset the cache between runs for isolation.

## Non-goals

- Connection pool tuning/production sizing (left to deployment config).
- Migration management (covered by SPEC-213 / ADR-012).

## Decision

`memory/store.py` additions:

```python
def get_engine() -> AsyncEngine | None: ...                       # lru_cache'd
def get_async_session_factory() -> async_sessionmaker | None: ... # lru_cache'd
async def get_db_session() -> AsyncGenerator[AsyncSession, None]: ...  # FastAPI dep
def reset_engine_cache() -> None: ...                              # test helper
```

`get_engine()` returns `None` when `DATABASE_URL` is unset in settings —
all persistence calls become no-ops in that mode, which is how tests and
local dev run without Postgres. When set, the engine is created once and
cached via `functools.lru_cache`; repeated calls return the same object.
`reset_engine_cache()` clears the cache for test isolation between test
modules that vary `DATABASE_URL`.

The app's `main.lifespan` calls `get_engine()` on startup (forcing creation
if configured) and disposes it on shutdown.

## Acceptance criteria

- [x] `get_engine()` returns `None` when `DATABASE_URL` unset
- [x] `get_engine()` returns an `AsyncEngine` when `DATABASE_URL` is set
- [x] `get_engine()` is idempotent (same object returned on repeated calls)
- [x] `reset_engine_cache()` clears the cache for test isolation
- [x] `main.lifespan` creates engine on startup, disposes on shutdown
- [x] `get_db_session()` yields a usable `AsyncSession`

## Testing

| Test | Covers |
|---|---|
| `test_get_engine_no_url_returns_none` | no DB graceful |
| `test_get_engine_idempotent` | cache hit |
| `test_reset_engine_cache` | test isolation |

## Open questions

- None — design is implemented and stable as of this writing.

## References

- [ADR-011: Memory engine + session factory wiring](../adr/ADR-011-memory-engine.md)
- `packages/maistro-core/src/maistro/memory/store.py`
