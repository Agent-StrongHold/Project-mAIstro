---
id: SPEC-249
title: "Memory exposure mode — write-authority gating primitive (ADR-057)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-011
  - maistro-engine#ADR-014
  - maistro-engine#ADR-034
implements:
  - maistro-engine#ADR-057
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-053
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests:
  - packages/maistro-core/tests/memory/test_exposure_mode.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-249: Memory exposure mode — write-authority gating primitive

## Context

ADR-057 requires a configurable, per-agent-instance switch for who holds write authority
over a memory block (`system_managed`, `agent_managed`, `hybrid`), without engine code ever
branching on product identity (ADR-019). Nothing implementing this exists today — memory
writes are implicitly agent-managed everywhere. This SPEC scopes the load-bearing gating
primitive: the `MemoryExposureMode`/`Actor` enums and a pure `enforce_write`/`enforce_promote`
gate that stores call before mutating. It does **not** rewrite `LearningStore`/`EpisodicStore`
to call the gate (that's per-store follow-up wiring, listed as non-goals below) — it adds the
primitive ADR-057 says must exist, matching this SPEC's role as the testable unit of the
ADR's decision.

## Goals

- Add `Actor` (`SYSTEM`, `AGENT`) and `MemoryExposureMode` (`SYSTEM_MANAGED`, `AGENT_MANAGED`,
  `HYBRID`) enums to `maistro/memory/exposure.py`.
- Add `MemoryWriteDenied` exception carrying `scope`, `actor`, `mode`, `reason`.
- Add `BlockExposure` (`SYSTEM_MANAGED`, `AGENT_MANAGED`) — the per-block tag used in `HYBRID`
  mode, separate from the per-instance `MemoryExposureMode` enum (their members overlap by
  name but they're distinct types: one is store-level config, the other a block attribute).
- Add pure functions `enforce_write(mode, actor, *, block_exposure=None) -> None` and
  `enforce_promote(mode, actor, *, block_exposure=None) -> None`: raise `MemoryWriteDenied` per
  the ADR-057 semantics table, return `None` (silently) when allowed. No I/O — callers invoke
  these before performing the actual write/promote and catch the exception.
- `HYBRID` mode requires `block_exposure` to be passed (raises `ValueError` if omitted) — the
  per-block tag determines the rule.

## Non-goals

- Wiring `enforce_write`/`enforce_promote` into `LearningStore`/`EpisodicStore`/the SQLAlchemy
  models — follow-up integration once products actually request non-default modes.
- `memory.write.denied` event emission (ADR-037) — follow-up once the event bus call site
  exists at an actual store boundary.
- Recipe-driven (`ADR-053` overlay) mode declaration/inheritance — follow-up; this SPEC adds
  the primitive the overlay would set.
- Migration/deprecation-warning behavior for agents that don't declare a mode — follow-up
  once an actual store wiring exists to warn from.
- `MemoryStore` Protocol changes (`read`/`write`/`promote` signatures) — deferred until a
  concrete store adopts the gate; adding unused Protocol methods now would be speculative.

## Decision

```python
# maistro/memory/exposure.py
class Actor(StrEnum):
    SYSTEM = "system"
    AGENT = "agent"

class MemoryExposureMode(StrEnum):
    SYSTEM_MANAGED = "system_managed"
    AGENT_MANAGED = "agent_managed"
    HYBRID = "hybrid"

class BlockExposure(StrEnum):
    SYSTEM_MANAGED = "system_managed"
    AGENT_MANAGED = "agent_managed"

@dataclass(frozen=True)
class MemoryWriteDenied(Exception):
    scope: str
    actor: Actor
    mode: MemoryExposureMode
    reason: str

def enforce_write(
    mode: MemoryExposureMode,
    actor: Actor,
    *,
    scope: str = "",
    block_exposure: BlockExposure | None = None,
) -> None: ...

def enforce_promote(
    mode: MemoryExposureMode,
    actor: Actor,
    *,
    scope: str = "",
    block_exposure: BlockExposure | None = None,
) -> None: ...
```

Semantics (ADR-057's table, implemented directly):
- `SYSTEM_MANAGED`: `AGENT` write/promote denied; `SYSTEM` write/promote allowed.
- `AGENT_MANAGED`: both actors allowed for write/promote.
- `HYBRID`: requires `block_exposure`; delegates to that tag's rule (`SYSTEM_MANAGED` tag →
  agent denied; `AGENT_MANAGED` tag → agent allowed). `SYSTEM` actor always allowed regardless
  of tag (matches the ADR's table: `write(... actor=SYSTEM)` is "allowed" in every mode/tag
  combination).

`enforce_write`/`enforce_promote` never touch state — pure validation, raise-or-return. Default
mode for new callers (no mode passed) is left to call sites per ADR-057's open question 2; this
SPEC does not bake in a default since no store wiring exists yet to need one.

## Acceptance criteria

- [x] `enforce_write(SYSTEM_MANAGED, AGENT)` raises `MemoryWriteDenied`.
- [x] `enforce_write(SYSTEM_MANAGED, SYSTEM)` returns `None`.
- [x] `enforce_write(AGENT_MANAGED, AGENT)` returns `None`.
- [x] `enforce_write(HYBRID, AGENT, block_exposure=BlockExposure.SYSTEM_MANAGED)` raises.
- [x] `enforce_write(HYBRID, AGENT, block_exposure=BlockExposure.AGENT_MANAGED)` returns `None`.
- [x] `enforce_write(HYBRID, AGENT)` (no `block_exposure`) raises `ValueError`.
- [x] `enforce_promote` mirrors `enforce_write`'s denial matrix exactly.
- [x] `MemoryWriteDenied` carries `scope`, `actor`, `mode`, `reason` and `reason` is non-empty.
- [x] Hypothesis property test: for every `(mode, actor, block_exposure)` combination, `SYSTEM`
      actor is never denied (matches ADR-057's table — system write is unconditionally allowed).

## Testing

- `packages/maistro-core/tests/memory/test_exposure_mode.py` (new) — unit tests for every
  mode/actor/tag combination in ADR-057's semantics table, the `HYBRID`-without-tag `ValueError`,
  and a Hypothesis property test for the "system never denied" invariant.

## Open questions

- Default mode for callers that don't specify one, and the deprecation-warning migration path
  for legacy agent-managed callers — deferred to the store-wiring follow-up SPEC, since no
  concrete store calls this gate yet.

## References

- `packages/maistro-core/src/maistro/memory/scopes.py`
- `packages/maistro-core/src/maistro/protocols/memory.py`
- [ADR-057: Memory exposure mode](../adr/ADR-057-memory-exposure-mode.md)
