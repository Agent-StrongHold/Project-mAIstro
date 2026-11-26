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
  - maistro-engine#ADR-092526-4391
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

- `can_read(reader: Principal, memory: EpisodicMemory) -> bool`: true iff the reader owns the memory
  on the owner axis at its own scope (USER-scope compares the canonical `user_id`, AGENT-scope
  compares `agent_id` — matching scope alone is not sufficient), or the memory is marked `shared`
  and the reader's scope is at-or-above the memory's origin scope.
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

## Amendment: same-user promotion (ADR-092526-4391, Proposed)

[ADR-092526-4391](../adr/ADR-092526-4391-same-user-user-model-promotion-is-self-consented.md)
proposes one case where this flow is not used. Promoting a fact scoped to a Workspace, Project or
AGENT into the **same authenticated user's** `UserModelFact` user model is automatic self-consent.
It writes an audit entry and creates no `ConsentTask`. Widening to another
user, or to TEAM, ORGANIZATION or GLOBAL scope, still requires the
`propose_widen -> resolve_consent -> apply_widen` flow above.

## Clarification: an authorized same-user agent read is not a cross-agent share

"Cross-agent sharing to another principal" and "an authorized Workspace Agent reading canonical
user-scope memory for the same authenticated user" are different cases, and only the first trips
the consent/shareable machinery of this SPEC:

- A Workspace Agent authorized as user *U* presents *U*'s canonical principal (`scope: USER`,
  `user_id: U`). Reading a USER-scope memory whose `user_id` is *U* is an **own-scope read**
  (`can_read` returns true through the exact-scope branch): no `ConsentTask`, no `shared` marker,
  and nothing is widened for any other principal.
- A read that reaches a **different principal** still follows this SPEC. Another user's memory
  needs consent ([ADR-092526-4391](../adr/ADR-092526-4391-same-user-user-model-promotion-is-self-consented.md)
  keeps cross-user widening behind `propose_widen -> resolve_consent -> apply_widen`), and another
  agent's AGENT-scope memory needs the owner to mark it shareable — even when both records belong
  to the same user. Authorization to act for a user is not authorization to read that user's
  agents' private memories.

Durable cross-Workspace reuse itself stays on canonical PostgreSQL/pgvector user-model state with
provenance, confidence and temporal semantics (ADR-092526-4391); Ladybug working memory remains a
disposable per-Workspace graph that is never traversed cross-Workspace.

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
- New unit tests pinning the same-user distinction: an authorized same-user Workspace Agent reads
  that user's USER-scope memory without a `shared` marker (and leaves it unshared); a different
  user's agent does not; and the user's Workspace Agent does not read another agent's AGENT-scope
  memory without sharing, even when both records belong to the same user.

## Open questions

- Whether a single `ConsentTask` widens scope for one memory or a batch ("share all my session
  learnings with the team") — left as single-memory for this SPEC; batch consent is a UX
  optimization for the hive-conductor application layer, not a core primitive change.

## References

- `packages/maistro-core/src/maistro/types/memory.py`
- [ADR-080: Memory Dynamics](../adr/ADR-080-memory-dynamics.md)
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
