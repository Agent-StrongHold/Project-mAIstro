---
id: SPEC-242
title: "Memory cross-scope sharing under owner consent (ADR-080 part C)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-068
implements:
  - maistro-engine#ADR-080
related:
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-241
  - maistro-engine#SPEC-243
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/memory/episodic/test_sharing.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-242: Memory cross-scope sharing under owner consent

## Context

ADR-080 part (C) specifies that a memory defaults to its origin scope (the
`global > org > team > user > agent > session` axes from ADR-013/068), that widening to a broader
scope requires a proactive consent task approved by the owner/admin, and that cross-agent reads
require the memory to be explicitly marked shareable — nothing leaks across a scope or agent
boundary by default. None of this exists today: `EpisodicMemory.scope` is set once at creation with
no widening workflow, and there is no consent-task queue.

## Goals

- `can_read(reader: Principal, memory: EpisodicMemory) -> bool`: true iff the reader's scope matches
  the memory's scope, or the memory is marked `shared` and the reader's scope is at-or-above the
  memory's origin scope.
- `propose_widen(memory, target_scope) -> ConsentTask`: builds a consent task naming the memory's
  summary and the proposed wider scope, addressed to the memory's owner/admin.
- A `ConsentTask` data shape and an `approve`/`reject` resolution path that, on approval, widens the
  memory's `scope` field (or sets a `shared`/`shared_with` marker) and, on rejection, leaves the
  memory at its origin scope unchanged.
- `EpisodicMemory` gains a `shared: bool` (or `shared_scope: MemoryScope | None`) field so reads can
  distinguish "this agent's own memory" from "explicitly shared with me."

## Non-goals

- Decay/reinforcement (SPEC-240) and consolidation (SPEC-241) — siblings, not dependencies here.
- Retrieval ranking (SPEC-243).
- The UI/notification surface that presents a `ConsentTask` to the owner — this SPEC defines the
  task data shape and resolution function; the actual "surface this in chat/dashboard" wiring is an
  application-layer (hive-conductor) concern.
- Tenant-hard isolation — that's Stronghold (ADR-019), not core.

## Decision

```python
@dataclass
class ConsentTask:
    memory_id: str
    summary: str
    current_scope: MemoryScope
    target_scope: MemoryScope
    owner: str                 # principal id of the approver
    status: Literal["pending", "approved", "rejected"] = "pending"

class Principal(Protocol):
    scope: MemoryScope
    agent_id: str | None
    user_id: str | None

def can_read(reader: Principal, memory: EpisodicMemory) -> bool: ...

def propose_widen(memory: EpisodicMemory, target_scope: MemoryScope) -> ConsentTask: ...

def resolve_consent(task: ConsentTask, decision: Literal["approve", "reject"]) -> ConsentTask: ...

def apply_widen(memory: EpisodicMemory, task: ConsentTask) -> EpisodicMemory:
    """Only callable when task.status == 'approved'; widens memory.scope to task.target_scope."""
```

Scope comparison uses the existing ordering `global > org > team > user > agent > session`
(ADR-013/068 axes) — `target_scope` must be broader-or-equal to `current_scope`, never narrower
(narrowing needs no consent, it's always safe).

## Acceptance criteria

- [x] `can_read` returns true for a reader in the memory's exact scope.
- [x] `can_read` returns true for a reader at-or-above the memory's scope only when `shared` is set;
      returns false otherwise (no default leakage across scope boundaries).
- [x] `can_read` returns false for a different agent reading another agent's memory unless the
      memory is explicitly marked shareable, regardless of scope.
- [x] `propose_widen` rejects (raises or returns an error) a `target_scope` narrower than the
      memory's current scope (raises `ScopeNarrowingError`).
- [x] `apply_widen` only takes effect when the `ConsentTask.status == "approved"`; calling it on a
      pending or rejected task is a no-op.
- [x] A rejected consent task leaves the memory's scope and `shared` flag unchanged.

## Testing

- New unit tests for `can_read` across same-scope, wider-shared, wider-unshared, and cross-agent
  cases.
- New unit tests for the `propose_widen` -> `resolve_consent` -> `apply_widen` flow, both approve and
  reject paths.

## Open questions

- Whether a single `ConsentTask` widens scope for one memory or a batch ("share all my session
  learnings with the team") — left as single-memory for this SPEC; batch consent is a UX
  optimization for the hive-conductor application layer, not a core primitive change.

## References

- `packages/maistro-core/src/maistro/types/memory.py`
- [ADR-080: Memory Dynamics](../adr/ADR-080-memory-dynamics.md)
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
