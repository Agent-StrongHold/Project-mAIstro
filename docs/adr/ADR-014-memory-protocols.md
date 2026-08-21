---
id: ADR-014
title: Memory protocols
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-013
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
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

# ADR-014: Memory protocols

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T2  
**Depends on:** ADR-013

---

## Context

No Protocol contracts for memory stores — makes testing via fakes impossible and prevents DI.

## Decision

Create `src/maistro/protocols/memory.py` with `LearningStore`, `EpisodicStore`, `OutcomeStore` as `@runtime_checkable Protocol`s.

## Interface

```python
# protocols/memory.py
@runtime_checkable class LearningStore(Protocol):
    async def store(self, learning: Learning) -> int: ...
    async def find_relevant(self, user_text: str, *, agent_id=None, org_id="", max_results=10) -> list[Learning]: ...
    async def mark_used(self, learning_ids: list[int]) -> None: ...
    async def check_auto_promotions(self, threshold=5, *, org_id="") -> list[Learning]: ...
    async def get_promoted(self, task_type=None, *, org_id="") -> list[Learning]: ...

@runtime_checkable class EpisodicStore(Protocol):
    async def store(self, memory: EpisodicMemory) -> str: ...
    async def retrieve(self, query: str, *, agent_id=None, user_id=None, team_id=None, org_id=None, limit=5) -> list[EpisodicMemory]: ...
    async def reinforce(self, memory_id: str, delta: float = 0.05) -> None: ...

@runtime_checkable class OutcomeStore(Protocol):
    async def record(self, outcome: Outcome) -> int: ...
    async def get_task_completion_rate(self, task_type="", days=7, org_id="") -> dict[str, Any]: ...
```

## Acceptance criteria

- [ ] `isinstance(InMemoryLearningStore(), LearningStore)` is `True`
- [ ] `isinstance(InMemoryEpisodicStore(), EpisodicStore)` is `True`
- [ ] `isinstance(InMemoryOutcomeStore(), OutcomeStore)` is `True`
- [ ] A stub class that only has some methods returns `False` for `isinstance`

## Source references

- `stronghold/src/stronghold/protocols/memory.py`
