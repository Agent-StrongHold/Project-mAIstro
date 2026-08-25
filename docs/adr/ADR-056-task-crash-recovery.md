---
id: ADR-056
title: Task crash recovery — durable resume with wave verification
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-13
substrate:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-018
  - maistro-engine#ADR-037
implements: []
related:
  - maistro-engine#ADR-049
  - maistro-engine#ADR-051
  - maistro-engine#ADR-052
  - maistro-engine#ADR-054
  - maistro-engine#ADR-055
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Implemented
---

# ADR-056: Task crash recovery — durable resume with wave verification

## Context

ADR-038 ships retry, circuit-breaker, fallback, idempotency-key contract for non-idempotent operations, and three-level health checks. ADR-018 persists `TaskRecord` fire-and-forget on submit/update. Neither specifies how the conductor recovers a **long-running, multi-step agent task** whose process dies mid-execution:

- A mid-flight irreversible tool call may have partially side-effected.
- Some parallel waves (ADR-052) may have completed; others not.
- Cumulative spend (ADR-054) must persist across the crash.
- The in-flight LLM call may have committed server-side without returning to us.
- A parallel non-dependent path waiting on an approval gate (ADR-051) must resume cleanly.

This ADR specifies task-level resume on top of ADR-038's primitives.

## Problem

No specified resumption semantics for long-running multi-step agent tasks across conductor crashes.

## Decision

Three layers, all on top of ADR-038 + ADR-018 + ADR-037 narrow event log.

### 1. Partial-execution recovery for irreversible tools (layered contract)

Layered per the tool's registered capabilities (extends ADR-050 and ADR-038):

- **Idempotency keys (preferred).** ADR-050 tool registration declares `idempotency_key`. Substrate passes the key on every irreversible call; tool guarantees same-key-same-result. Re-issue always safe on resume.
- **Pre-commit log + external verification (backstop).** ADR-050 tool registration declares `verify_side_effect`. Before each irreversible call, substrate logs intent (`tool.call.about_to_fire`) to the narrow event log. On resume, if `about_to_fire` has no matching `done`, substrate calls `verify_side_effect` to check whether the effect landed before deciding to re-issue.
- **Bubble-up (fallback).** If a tool has neither, substrate escalates via the ADR-051 approval surface: "this tool was mid-flight on crash — retry / skip / I-checked-manually-mark-done." Reuses the same UI surface as ADR-051 approval gates.

Substrate routes to the highest available tier per tool.

### 2. Wave resumption with verification

For multi-wave tasks (ADR-052), at resume:

- **Completed waves**: re-validate each. Assert the wave's shadow-git branch HEAD matches the SHA recorded in the wave's checkpoint. Assert no orphaned `tool.call.about_to_fire` events exist after the wave's `wave.completed` event. Assert recipe version and code-registry versions (ADR-053) used by the wave are still present and compatible. Any drift → demote the wave to incomplete and re-run.
- **Incomplete waves**: re-run from the wave's last checkpoint.

### 3. Resume trigger

Auto-resume on conductor restart, gated by a crash-loop circuit breaker. Reuse ADR-038 defaults: `N=5` crashes in `W=60s` quarantines the task. A quarantined task does not auto-resume; an operator inspects via `/v1/tasks/{id}/recovery` and either resumes manually or marks failed.

### Checkpoint stream

The `TaskRecord` (ADR-018) gains a sibling `task_checkpoints` table — narrow event log entries flagged as resumption-critical. Recorded events:

- `tool.call.about_to_fire` / `tool.call.done`
- `wave.fan_out` / `wave.completed` / `wave.failed`
- `approval.gate.{raised,answered}`
- `spend.update`
- `memory.promote`

On resume, substrate replays the checkpoint stream up to the last consistent state; resumption picks up from there. (This is **state-replay**; not the orchestration-debugging replay of ADR-055. Same event log; distinct operation.)

## Interface (sketch)

```python
class TaskCheckpoint(BaseModel):
    task_id: UUID
    sequence: int                # monotonic per task
    kind: Literal[
        "tool_call.about_to_fire", "tool_call.done",
        "wave.fan_out", "wave.completed", "wave.failed",
        "approval.gate.raised", "approval.gate.answered",
        "spend.update", "memory.promote",
    ]
    payload: dict[str, Any]
    recipe_version: str          # for cross-version-resume safety
    code_registry_version: str
    created_at: datetime

class TaskRecovery(Protocol):
    async def resumable_tasks(self) -> list[TaskRecord]: ...
    async def resume(self, task_id: UUID) -> ResumeResult: ...
    async def quarantine(self, task_id: UUID, reason: str) -> None: ...
```

## Acceptance criteria

- [ ] Conductor restart auto-resumes all non-terminal tasks (sequenced by `last_updated_at`).
- [ ] Crash-loop circuit breaker: N=5 crashes in W=60s quarantines (matches ADR-038 defaults).
- [ ] Quarantined tasks not auto-resumed; surfaced via `/v1/tasks/recovery`.
- [ ] Mid-flight irreversible call with `idempotency_key` re-issues safely on resume.
- [ ] Mid-flight irreversible call with `verify_side_effect` queries before deciding re-issue.
- [ ] Mid-flight irreversible call with neither bubbles to the ADR-051 approval surface.
- [ ] Completed wave with verified shadow-git branch trusted on resume; mismatched branch demoted.
- [ ] Recipe / code-registry version drift between original execution and resume → wave demoted; cross-version task resume refused with explicit error.
- [ ] Cumulative spend (ADR-054) survives crash; resumed task starts at pre-crash percentage.
- [ ] Event `task.resume.{started,completed,quarantined}` per ADR-037.
- [ ] Hypothesis property test on checkpoint replay: any valid checkpoint sequence yields a consistent task state.

## Open questions

1. **Auto-resume on conductor restart vs operator-triggered.** Recommend auto with crash-loop quarantine — matches the pattern users expect from durable workflow engines.
2. **Checkpoint compaction.** Old completed-task checkpoints — retain indefinitely or compact? Recommend tier-driven retention via the sensitivity tag (ADR-055).
3. **Cross-version resume policy.** Recommend strict refusal; surface a clear error and let the operator decide between manual recovery or task abort.
4. **Multi-conductor (HA) resume.** Out of scope — single-conductor for v0. Multi-replica with leader election deferred to a follow-up ADR.
5. **Approval-gate state at crash.** A task waiting on an approval that was answered just before crash — the answer is in the event log but unprocessed. Recommend resume replays the answer and continues.

## Source references

- ADR-038 reliability primitives (retry, circuit-breaker, idempotency-key contract).
- ADR-018 `TaskRecord` persistence (gains `cumulative_spend`, `workspace_ref`, checkpoint stream).
- ADR-049 shadow git (the wave branch SHAs that verification compares against).
- ADR-050 tool registration capabilities (idempotency_key, verify_side_effect).
- ADR-051 approval gate UI surface (reused for bubble-up).
- ADR-052 parallel waves (the per-wave branches resume targets).
- ADR-054 cumulative-spend persistence.
- ADR-055 narrow event log (the source of the checkpoint stream).
- `maistro-engine:src/maistro/tasks/runner.py`.

## Out of scope

- Disaster recovery / multi-region failover (stronghold concern).
- Cross-task state replay (each task resumes independently).
- Speculative resumption on a different node while the original may still be alive.
- Deterministic re-execution of LLM outputs (ADR-055 out of scope).
