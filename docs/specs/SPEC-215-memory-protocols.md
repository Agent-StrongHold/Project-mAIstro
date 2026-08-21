---
id: SPEC-215
title: "Memory store protocols: LearningStore, EpisodicStore, OutcomeStore"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-20
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-014
implements:
  - maistro-engine#ADR-014
related:
  - maistro-engine#SPEC-214
  - maistro-engine#SPEC-216
  - maistro-engine#SPEC-217
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-215: Memory store protocols: LearningStore, EpisodicStore, OutcomeStore

## Context

Without `Protocol` contracts for memory stores, business logic that depends
on memory persistence could only be tested against concrete implementations
— no fakes/stubs for unit tests, and no dependency-injection boundary
between "a memory store" and "the in-memory or Postgres implementation of
one." ADR-014 decided to define `LearningStore`, `EpisodicStore`, and
`OutcomeStore` as `@runtime_checkable` Protocols in `protocols/memory.py`.

## Goals

- Structural typing contracts for the three memory store roles so callers
  depend on the Protocol, never a concrete class.
- `@runtime_checkable` so `isinstance()` checks work for test assertions and
  defensive runtime guards.

## Non-goals

- Concrete store implementations (covered by SPEC-216 for `LearningStore`,
  SPEC-217 for `OutcomeStore`; episodic store implementation is out of scope
  for this spec cluster).

## Decision

`maistro/protocols/memory.py` defines:

```python
@runtime_checkable
class LearningStore(Protocol):
    async def store(self, learning: Learning) -> int: ...
    async def find_relevant(self, user_text: str, *, agent_id=None, org_id="", max_results=10) -> list[Learning]: ...
    async def mark_used(self, learning_ids: list[int]) -> None: ...
    async def check_auto_promotions(self, threshold=5, *, org_id="") -> list[Learning]: ...
    async def get_promoted(self, task_type=None, *, org_id="") -> list[Learning]: ...

@runtime_checkable
class EpisodicStore(Protocol):
    async def store(self, memory: EpisodicMemory) -> str: ...
    async def retrieve(self, query: str, *, agent_id=None, user_id=None, team_id=None, org_id=None, limit=5) -> list[EpisodicMemory]: ...
    async def reinforce(self, memory_id: str, delta: float = 0.05) -> None: ...

@runtime_checkable
class OutcomeStore(Protocol):
    async def record(self, outcome: Outcome) -> int: ...
    async def get_task_completion_rate(self, task_type="", days=7, org_id="") -> dict[str, Any]: ...
```

The implemented module additionally defines `mark_outcome`/`list_all` on
`LearningStore`, and several extra methods on `OutcomeStore`
(`get_experience_context`, `get_usage_breakdown`, `get_daily_timeseries`,
`list_outcomes`) plus unrelated protocols (`LearningExtractor`,
`SkillMutationStore`, `RCAExtractor`, `SessionStore`, `AuditLog`) that grew
in the same module after ADR-014 was accepted — these are later additions,
not part of this spec's scope, and are not enumerated in the acceptance
criteria below.

## Acceptance criteria

- [x] `isinstance(InMemoryLearningStore(), LearningStore)` is `True`
- [x] `isinstance(InMemoryEpisodicStore(), EpisodicStore)` is `True`
- [x] `isinstance(InMemoryOutcomeStore(), OutcomeStore)` is `True`
- [x] A stub class implementing only some of a Protocol's methods returns
      `False` for `isinstance`

## Testing

No dedicated protocol-conformance test file was located; conformance is
exercised indirectly via the concrete store test suites
(`tests/memory/learnings/test_learning_store.py`,
`packages/maistro-core/tests/memory/...`).

## Open questions

- None — design is implemented and stable as of this writing.

## References

- [ADR-013: Memory types](../adr/ADR-013-memory-types.md)
- [ADR-014: Memory protocols](../adr/ADR-014-memory-protocols.md)
- `packages/maistro-core/src/maistro/protocols/memory.py`
