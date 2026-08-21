---
id: SPEC-211
title: "Lane-based task scheduling: LIVE fast-lane vs BACKGROUND pool"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-20
substrate:
  - maistro-engine#ADR-004
  - maistro-engine#ADR-010
implements:
  - maistro-engine#ADR-010
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
---

# SPEC-211: Lane-based task scheduling: LIVE fast-lane vs BACKGROUND pool

## Context

`TaskRunner` (`maistro.tasks.runner`) treats all tasks with equal priority,
so interactive (live-chat) requests and batch background jobs contend for
the same worker pool — interactive users see latency spikes when the
pool is saturated by background work. ADR-010 decided to use the
already-existing `Lane` axis (`AgentSpec.lane`, defined in ADR-004) to
reserve a fast-lane slot allocation for `Lane.LIVE` tasks, separate from
the `Lane.BACKGROUND` pool.

**Implementation status:** the `Lane` enum and `AgentSpec.lane` field
(default `Lane.BACKGROUND`) exist in
`maistro.agents.spec.agent_spec`. The `TaskRunner` lane-aware slot
splitting (`live_slots` / `background_slots`) described below has **not**
been implemented — `TaskRunner` currently has a single `max_workers`
semaphore with no lane awareness. This spec documents the still-pending
design so it can be picked up as a discrete unit of work.

## Goals

- Reserve worker capacity for `Lane.LIVE` tasks so they are not blocked
  behind a saturated `Lane.BACKGROUND` queue.
- Default new tasks to `Lane.BACKGROUND` so unmodified callers see no
  behavior change.
- Surface the lane a task ran on in the task status API.

## Non-goals

- Preemption of already-running tasks (not safe without cooperative yield
  points — explicitly out of scope per ADR-010).
- Dynamic/adaptive slot rebalancing — the LIVE/BACKGROUND split is a fixed
  construction-time parameter.

## Decision

`TaskRunner` gains two slot pools instead of one `max_workers` semaphore:

```python
class TaskRunner:
    live_slots: int = 2                    # reserved for Lane.LIVE
    background_slots: int                  # = max_workers - live_slots
```

A task's `Lane` (from `AgentSpec.lane`) determines which semaphore it
acquires before execution. Callers tag lane at task-creation time:

- `api/chat_completions.py` → tags spawned tasks `Lane.LIVE`.
- `api/tasks.py` → tags tasks `Lane.BACKGROUND` by default (existing
  callers unaffected).

`GET /tasks/{id}` exposes the lane via a new optional `TaskResponse.lane`
field (`None` for tasks created before this field existed).

## Acceptance criteria

- [ ] `TaskRunner` splits `max_workers` into `live_slots` (default 2) and
      `background_slots` (`max_workers - live_slots`)
- [ ] `chat_completions` endpoint tags spawned tasks as `Lane.LIVE`
- [ ] `tasks` API endpoint tags tasks as `Lane.BACKGROUND` by default
- [ ] A LIVE task runs immediately even when the BACKGROUND queue is full
- [ ] `TaskResponse` serializes the `lane` field

## Testing

| Test | Covers |
|---|---|
| `test_live_task_bypasses_background_queue` | slot isolation |
| `test_background_task_default_lane` | default lane |
| `test_task_response_lane_field` | serialization |

## Open questions

- `TaskRunner`'s lane-aware slot splitting is unimplemented; this spec's
  acceptance criteria are the build target, not a record of existing
  behavior. Confirm `live_slots=2` is still the right fixed reservation
  before implementing, since current worker-pool sizing
  (`DEFAULT_MAX_WORKERS=4`) was chosen without lane contention in mind.

## References

- [ADR-004: Agent spec](../adr/ADR-004-agent-spec.md)
- [ADR-010: Lane-based scheduling (LIVE vs BACKGROUND)](../adr/ADR-010-lane-scheduling.md)
- `packages/maistro-core/src/maistro/agents/spec/agent_spec.py` (`Lane` enum)
- `packages/maistro-core/src/maistro/tasks/runner.py` (`TaskRunner`, not yet lane-aware)
