---
id: ADR-010
title: Lane-based scheduling (LIVE vs BACKGROUND)
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-004
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-010: Lane-based scheduling (LIVE vs BACKGROUND)

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T1  
**Depends on:** ADR-004

---

## Context

maistro-engine runs all tasks with equal priority. Interactive (live-chat) requests and batch background jobs contend for the same worker pool, causing latency spikes for interactive users.

## Decision

`Lane` enum (already in `AgentSpec` from ADR-004) is the scheduling axis. The `TaskRunner` gains lane-awareness: LIVE tasks get a reserved fast-lane slot; BACKGROUND tasks use the remaining pool. Default lane is `BACKGROUND` so existing behaviour is unchanged.

Concretely: `TaskRunner` splits `max_workers` into `live_slots=2` and `background_slots=max_workers-2`. A task's `AgentSpec.lane` propagates from the HTTP request (`chat_completions` → LIVE, `tasks` API → BACKGROUND per caller).

## Interface

```python
# tasks/runner.py — additions only
class TaskRunner:
    live_slots: int = 2          # reserved for Lane.LIVE
    background_slots: int        # = max_workers - live_slots

# api/chat_completions.py — already creates tasks; tag them LIVE
# api/tasks.py — tag tasks BACKGROUND by default
```

`Lane` is surfaced in `GET /tasks/{id}` response via `TaskResponse.lane` field (new optional field, None for existing tasks).

## Acceptance criteria

- [ ] `chat_completions` endpoint tags spawned tasks as LIVE
- [ ] `tasks` API endpoint tags tasks as BACKGROUND by default
- [ ] A LIVE task runs immediately even when BACKGROUND queue is full
- [ ] `TaskResponse` serializes `lane` field

## Test plan

| Test | Covers |
|---|---|
| `test_live_task_bypasses_background_queue` | slot isolation |
| `test_background_task_default_lane` | default lane |
| `test_task_response_lane_field` | serialization |

## Out of scope

Preemption of running tasks (not safe to implement without cooperative yield points).

## Source references

- `Project_mAIstro/conductor/orchestrator/agents/agent_spec.py:Lane`
