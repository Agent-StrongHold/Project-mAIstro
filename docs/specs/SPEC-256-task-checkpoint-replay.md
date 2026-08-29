---
id: SPEC-256
title: "Task crash recovery — checkpoint replay and crash-loop quarantine core (ADR-056)"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-06-20
history:
  - status: Accepted
    date: 2026-06-20
  - status: AC Defined
    date: 2026-08-29
substrate:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-018
related:
  - maistro-engine#SPEC-254
  - maistro-engine#SPEC-255
  - maistro-engine#ADR-051
  - maistro-engine#ADR-054
implements:
  - maistro-engine#ADR-056
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/tasks/test_checkpoint_replay.py
  - packages/maistro-core/tests/orchestrator/waves/test_recovery_compatibility.py
source:
  - packages/maistro-core/src/maistro/tasks/recovery.py
ac-modules:
  AC-1: maistro.orchestrator.waves.ensemble
  AC-2: maistro.orchestrator.waves.ensemble
  AC-3: maistro.orchestrator.waves.ensemble
  AC-4: maistro.orchestrator.waves.ensemble
  AC-5: maistro.tasks.replay
  AC-6: maistro.orchestrator.waves.ensemble
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-256: Task crash recovery — checkpoint replay and crash-loop quarantine core

## Context

ADR-056 requires the conductor to resume a long-running task from a durable checkpoint stream
after a crash, demoting waves whose state has drifted and quarantining tasks that crash-loop. No
`TaskCheckpoint` type or replay logic exists today. This SPEC scopes the pure, store-agnostic
core: given an ordered checkpoint sequence, compute the resulting task state (open tool calls,
wave statuses, last-answered approval, cumulative spend) a resume operation would pick up from —
and the crash-loop quarantine decision, reusing `maistro.agents.circuit_breaker.CircuitBreaker`
exactly as ADR-056 directs ("matches ADR-038 defaults") rather than reimplementing it.

## Goals

- Add `maistro/tasks/checkpoint.py`: `CheckpointKind` (`StrEnum`: `TOOL_CALL_ABOUT_TO_FIRE`,
  `TOOL_CALL_DONE`, `WAVE_FAN_OUT`, `WAVE_COMPLETED`, `WAVE_FAILED`, `APPROVAL_GATE_RAISED`,
  `APPROVAL_GATE_ANSWERED`, `SPEND_UPDATE`, `MEMORY_PROMOTE`), `TaskCheckpoint` (frozen
  dataclass: `task_id: str`, `sequence: int`, `kind: CheckpointKind`, `payload: dict[str, Any]`,
  `recipe_version: str`, `code_registry_version: str`, `created_at: datetime`).
- Add `maistro/tasks/replay.py`: `ResumeState` (frozen dataclass: `open_tool_calls:
  frozenset[str]`, `wave_status: dict[str, str]`, `cumulative_spend: float`,
  `pending_approval_gates: frozenset[str]`) and `replay(checkpoints: tuple[TaskCheckpoint, ...])
  -> ResumeState` — a pure left-fold over `checkpoints` sorted by `sequence`:
  - `TOOL_CALL_ABOUT_TO_FIRE{call_id}` adds `call_id` to `open_tool_calls`;
    `TOOL_CALL_DONE{call_id}` removes it. A `call_id` left in `open_tool_calls` at the end of
    the fold is exactly the "mid-flight on crash" set ADR-056 routes through the layered
    recovery contract (idempotency key / verify_side_effect / bubble-up — all out of scope here,
    see Non-goals; this function only identifies *which* calls need that routing).
  - `WAVE_FAN_OUT{wave_id}` sets `wave_status[wave_id] = "running"`; `WAVE_COMPLETED{wave_id}`
    sets `"completed"`; `WAVE_FAILED{wave_id}` sets `"failed"`.
  - `APPROVAL_GATE_RAISED{gate_id}` adds `gate_id` to `pending_approval_gates`;
    `APPROVAL_GATE_ANSWERED{gate_id}` removes it (per ADR-056's open-question resolution: "resume
    replays the answer and continues" — a gate answered just before crash is not left pending).
  - `SPEND_UPDATE{delta}` accumulates into `cumulative_spend` (additive; resumed task starts at
    the pre-crash total per ADR-056's acceptance criteria).
  - `MEMORY_PROMOTE` checkpoints are accepted (kind recognized, payload validated by shape only)
    but produce no `ResumeState` field in this SPEC's scope — memory-side replay is
    `maistro.memory`'s concern, not the task-resume state machine (see Non-goals).
- Add `maistro/tasks/recovery.py`: `CrashLoopPolicy` wrapping a `CircuitBreaker` —
  `record_crash(breaker: CircuitBreaker) -> None` calls `breaker.record_failure()`;
  `should_quarantine(breaker: CircuitBreaker) -> bool` returns `not breaker.allow_request()`.
  Construct the breaker with ADR-038/ADR-056's stated defaults (`failure_threshold=5`,
  `recovery_timeout=60`) at the call site — this module does not hardcode a singleton, consistent
  with `CircuitBreaker` being a per-resource instance elsewhere in the codebase.
- Add a version-drift check: `version_compatible(checkpoint: TaskCheckpoint, *,
  current_recipe_version: str, current_code_registry_version: str) -> bool` — returns `False` if
  either version differs from the checkpoint's recorded version, per ADR-056's "cross-version
  task resume refused with explicit error" acceptance criterion (this function makes the boolean
  decision; raising/surfacing the explicit error is the resume call site's job).

## Non-goals

- `TaskRecovery` Protocol's `resumable_tasks()`/`resume()`/`quarantine()` orchestration —
  database queries, actually re-issuing tool calls, and the `/v1/tasks/{id}/recovery` route are
  follow-up once a persistence layer for `task_checkpoints` exists (ADR-018 extension).
  `replay()` is the pure function that orchestration layer will call.
- The layered idempotency-key / verify_side_effect / bubble-up routing for mid-flight irreversible
  calls (ADR-056 layer 1) — this SPEC identifies the `open_tool_calls` set; routing each one
  through ADR-050's registered capabilities is a separate integration once SPEC-252's registry
  and a real tool-dispatch call site are wired together.
- Shadow-git branch-SHA verification for completed waves (ADR-056 layer 2's drift check against
  SPEC-254/255) — `wave_status` here only tracks the checkpoint-log-derived status string;
  comparing it against the actual shadow-git branch HEAD is a follow-up once a resume call site
  has both the checkpoint state and a live `ShadowGitWorkspace` to compare against.
- `task.resume.{started,completed,quarantined}` events (ADR-037 wiring) — follow-up.
- Hypothesis property test claimed by ADR-056 ("any valid checkpoint sequence yields a consistent
  task state") is included here (see Acceptance criteria) using a generated-checkpoint-sequence
  strategy restricted to well-formed `about_to_fire`/`done` and `raised`/`answered` pairing.
- `task_checkpoints` table schema / persistence — in-memory tuples only in this SPEC.

## Decision

```python
# maistro/tasks/checkpoint.py
class CheckpointKind(StrEnum):
    TOOL_CALL_ABOUT_TO_FIRE = "tool_call.about_to_fire"
    TOOL_CALL_DONE = "tool_call.done"
    WAVE_FAN_OUT = "wave.fan_out"
    WAVE_COMPLETED = "wave.completed"
    WAVE_FAILED = "wave.failed"
    APPROVAL_GATE_RAISED = "approval.gate.raised"
    APPROVAL_GATE_ANSWERED = "approval.gate.answered"
    SPEND_UPDATE = "spend.update"
    MEMORY_PROMOTE = "memory.promote"

@dataclass(frozen=True)
class TaskCheckpoint:
    task_id: str
    sequence: int
    kind: CheckpointKind
    payload: dict[str, Any]
    recipe_version: str
    code_registry_version: str
    created_at: datetime

# maistro/tasks/replay.py
@dataclass(frozen=True)
class ResumeState:
    open_tool_calls: frozenset[str]
    wave_status: dict[str, str]
    cumulative_spend: float
    pending_approval_gates: frozenset[str]

def replay(checkpoints: tuple[TaskCheckpoint, ...]) -> ResumeState: ...

# maistro/tasks/recovery.py
class CrashLoopPolicy:
    def record_crash(self, breaker: CircuitBreaker) -> None: ...
    def should_quarantine(self, breaker: CircuitBreaker) -> bool: ...

def version_compatible(checkpoint, *, current_recipe_version, current_code_registry_version) -> bool: ...
```

## Acceptance criteria

The list below is about the pure functions, and every claim in it was true. What
was missing is a caller: `version_compatible` and `CrashLoopPolicy` had none, so
recovery resumed a checkpoint without comparing the versions the checkpoint
itself recorded, and a task that crashed during recovery was recovered again on
every restart. #624 wired them and states those criteria here, in the form the
AC gate reads.

```gherkin
@AC-1
Scenario: A checkpoint from another recipe version is not resumed
  Given checkpoints recorded under one recipe version
  When recovery runs under a different recipe version
  Then the saved results are not returned as the answer
  And the refusal names the recorded version and the running one

@AC-2
Scenario: A checkpoint from another code registry version is not resumed
  Given checkpoints recorded under one code registry version
  When recovery runs under a different code registry version
  Then the saved results are not returned as the answer

@AC-3
Scenario: A matching checkpoint still recovers
  Given checkpoints recorded under the running configuration
  When recovery runs
  Then the saved results are returned without re-running any wave

@AC-4
Scenario: Repeated recovery quarantines the task
  Given a task recovered more times than the configured limit without completing
  When recovery runs again
  Then it refuses, distinguishably from having nothing to recover
  And a task with no checkpoints is never quarantined

@AC-5
Scenario: An interruption before completion reports what it left open
  Given checkpoints recording an open tool call, a raised approval gate and spend
  And no completion marker
  When recovery runs
  Then the folded state carries that open call, that pending gate and that spend
  And folding the checkpoints the ensemble actually writes does not raise

@AC-6
Scenario: The recovery decision is on the event stream
  When recovery resumes, refuses or quarantines
  Then it emits a canonical event saying which, and why
```

### Pure-function claims verified by `test_checkpoint_replay.py`

- [x] A `TOOL_CALL_ABOUT_TO_FIRE` with a matching later `TOOL_CALL_DONE` leaves that call out of
      `open_tool_calls`; one with no matching `done` leaves it in.
- [x] `WAVE_FAN_OUT` → `WAVE_COMPLETED` for a wave yields `wave_status[wave_id] == "completed"`;
      `WAVE_FAN_OUT` alone (no terminal event) yields `"running"`.
- [x] An `APPROVAL_GATE_RAISED` immediately followed by `APPROVAL_GATE_ANSWERED` (even at the very
      end of the sequence) leaves that gate out of `pending_approval_gates`.
- [x] `SPEND_UPDATE` checkpoints accumulate additively; resumed `cumulative_spend` equals the sum
      of all deltas regardless of how many updates occurred.
- [x] `replay(())` (empty sequence) returns a `ResumeState` with all-empty/zero fields.
- [x] Checkpoints out of `sequence` order in the input tuple are replayed in `sequence` order, not
      input order.
- [x] `CrashLoopPolicy.should_quarantine` is `False` until 5 crashes are recorded, then `True`
      (matching `CircuitBreaker(failure_threshold=5)`'s existing semantics — this SPEC adds no new
      threshold logic, just names the call pattern ADR-056 specifies).
- [x] `version_compatible` returns `False` if either `recipe_version` or `code_registry_version`
      differs from the checkpoint's recorded values; `True` if both match.
- [x] Property test (Hypothesis): for any well-formed sequence of paired
      `about_to_fire`/`done` and `raised`/`answered` events (each pairing same-id, `done`/
      `answered` always at a `sequence` after its opener), `replay()` never leaves a *closed* pair
      in the open set.

## Testing

- `packages/maistro-core/tests/tasks/test_checkpoint_replay.py` (new) — replay-fold matrix above,
  out-of-order sequencing, `CrashLoopPolicy` threshold reuse of the existing `CircuitBreaker`,
  `version_compatible` matrix, and the Hypothesis property test.

## Open questions

- Whether `MEMORY_PROMOTE` checkpoints should feed a `ResumeState` field once `maistro.memory`
  has a replay consumer — deferred; accepting and validating the kind now means no checkpoint
  schema migration is needed when that consumer exists.

## References

- [ADR-056: Task crash recovery](../adr/ADR-056-task-crash-recovery.md)
- [SPEC-254: Shadow git workspace](SPEC-254-shadow-git-workspace.md)
- [SPEC-255: Parallel wave fan-in](SPEC-255-parallel-wave-fan-in.md)
- `packages/maistro-core/src/maistro/agents/circuit_breaker.py`
