---
id: ADR-018
title: Persist TaskRecord at queue/runner boundaries
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-011
  - maistro-engine#ADR-012
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
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

# ADR-018: Persist TaskRecord at queue/runner boundaries

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T2  
**Depends on:** ADR-011, ADR-012

---

## Context

`TaskRecord` SQLAlchemy model is defined but never written to. Task state lives only in `TaskQueue` (in-memory). On restart, all task history is lost.

## Decision

Add a thin persistence layer: when `get_async_session_factory()` returns a factory (i.e., a real DB is configured), `TaskQueue` upserts a `TaskRecord` on every `submit()` and `update_status()` call. Uses SQLAlchemy `merge()` (upsert by primary key). Failures are logged and swallowed — task execution must not fail because DB is unavailable.

This is fire-and-forget (no await blocking the hot path) — persistence is best-effort.

## Acceptance criteria

- [ ] When DB is absent (engine=None), `submit()` and `update_status()` work normally
- [ ] No test regression from TaskQueue changes
- [ ] `TaskRecord` row exists after `submit()` when DB configured (integration test)

## Test plan

All existing queue tests must still pass. The fire-and-forget persistence path is verified by checking no exception is raised.

## Source references

- `./src/maistro/tasks/queue.py`
- `./src/maistro/memory/store.py`
