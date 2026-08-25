---
id: ADR-057
title: Memory exposure mode — configurable system-managed vs agent-managed
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-13
substrate:
  - maistro-engine#ADR-011
  - maistro-engine#ADR-014
  - maistro-engine#ADR-034
implements: []
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-053
  - maistro-engine#SPEC-062126-6a31
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Implemented
---

# ADR-057: Memory exposure mode — configurable system-managed vs agent-managed

## Context

ADR-011/013/014/015/016/017 define the engine's canonical memory primitives (learnings, episodic, scopes, outcomes). ADR-034 names the engine the canonical owner. Today the memory protocols are read/write/consolidate from the substrate's perspective — there is no parameterised switch for **who** holds write authority over a memory block:

- **Agent-managed.** Agent reads its own state, decides what to write, decides what to promote from working memory to long-term. Matches the autonoetic loop that `packages/maistro-turing/` already runs.
- **System-managed.** Admin or operator curates blocks (templates, policy, persona context). Agent reads but cannot write or promote. Matches a hypothetical curated-context product where memory shape is part of admin configuration.

The four-repo governance (ADR-019, ADR-030) says the engine is product-agnostic; ADR-034 says the engine owns memory canonically. Both apply: the engine **must ship both modes as a configurable primitive**, then let each consumer pick — without the engine knowing which product is which.

## Problem

No parameterised control over agent write authority on memory. Consumer products either inherit one fixed semantic (today: implicit agent-managed) or fork the memory module.

## Decision

A `MemoryExposureMode` enum, configurable per agent instance and inheritable from recipes via ADR-053 overlay:

```python
class MemoryExposureMode(StrEnum):
    SYSTEM_MANAGED = "system_managed"  # admin-curated blocks; agent read-only
    AGENT_MANAGED = "agent_managed"    # agent reads + writes + promotes
    HYBRID = "hybrid"                  # per-block exposure tags; default SYSTEM_MANAGED
```

Mode is **per-agent-instance**, not global. Each product (maistro-turing autonoetic agents → `AGENT_MANAGED`; a future curated-context product → `SYSTEM_MANAGED`; canvas Da Vinci agent → its choice) picks at instantiation. Engine code never inspects product identity (ADR-019 / ADR-030 governance).

Mode semantics:

| Mode | `read(scope, query)` | `write(scope, block, actor=AGENT)` | `write(scope, block, actor=SYSTEM)` | `promote(block_id, actor=AGENT)` |
|---|---|---|---|---|
| `SYSTEM_MANAGED` | allowed | denied | allowed | denied |
| `AGENT_MANAGED` | allowed | allowed | allowed | allowed |
| `HYBRID` | allowed | per-block `exposure` tag | allowed | per-block tag |

In `HYBRID`, each `MemoryBlock` carries an `exposure: SYSTEM_MANAGED | AGENT_MANAGED` tag at definition time; the store enforces per-block rules.

Default for new agents: `SYSTEM_MANAGED`. Agents must explicitly opt into write authority. Existing agents in the codebase that don't declare a mode get `AGENT_MANAGED` on first read (back-compat) with a deprecation warning; v2.0 makes the declaration mandatory.

## Interface (sketch)

```python
class Actor(StrEnum):
    SYSTEM = "system"
    AGENT = "agent"

class MemoryStore(Protocol):   # extends existing ADR-014 protocols
    exposure_mode: MemoryExposureMode

    async def read(self, scope: MemoryScope, query: str) -> list[MemoryBlock]: ...
    async def write(self, scope: MemoryScope, block: MemoryBlock, *, actor: Actor) -> WriteResult: ...
    async def promote(self, block_id: UUID, *, actor: Actor) -> PromoteResult: ...

class MemoryWriteDenied(Exception):
    scope: MemoryScope
    actor: Actor
    mode: MemoryExposureMode
    reason: str
```

Recipe declares (merge: replace per ADR-053):

```yaml
memory:
  exposure_mode: system_managed | agent_managed | hybrid
```

## Acceptance criteria

- [ ] Agent `write` under `SYSTEM_MANAGED` raises `MemoryWriteDenied`.
- [ ] System `write` under any mode succeeds (subject to existing scope rules).
- [ ] Agent `write` under `AGENT_MANAGED` succeeds and persists.
- [ ] `HYBRID` mode honours per-block `exposure` tags.
- [ ] Mode recorded on the agent instance and on every memory event (`memory.read`, `memory.write`, `memory.promote`) per ADR-037.
- [ ] Event `memory.write.denied{scope, actor, mode, reason}` on denial.
- [ ] No engine code path branches on product identity to pick a mode (governance check; CI grep).
- [ ] Recipe-declared `memory.exposure_mode` honoured via ADR-053 overlay rendering.
- [ ] Hypothesis property test: for any sequence of mode-respecting operations, store state remains consistent with the mode's invariants.

## Open questions

Resolved by maistro-engine#SPEC-062126-6a31:

1. **Hybrid as a distinct enum value vs emergent from per-block tags.** Resolved: keep `HYBRID` explicit, as recommended.
2. **Default mode for new agents.** Resolved: moot — there is no implicit default at all (see #3); every agent declares explicitly.
3. **Migration for existing agents that don't declare a mode.** Resolved: mandatory declaration, no implicit fallback, no deprecation window — supersedes this ADR's own "implicit AGENT_MANAGED + deprecation warning" recommendation. An undeclared mode raises `MemoryUndeclaredModeError` immediately. maistro-turing's recipes gain an explicit `agent_managed` declaration in the same change.
4. **Per-scope mode override.** Resolved: agent-instance-level only for v0, as recommended.
5. **Memory promotion under `SYSTEM_MANAGED`.** Resolved: admin-only for v0, as recommended.

## Source references

- ADR-011 memory engine.
- ADR-014 memory protocols.
- ADR-034 memory canonical ownership.
- `maistro-engine:src/maistro/memory/`.
- `maistro-engine:packages/maistro-turing/src/maistro_turing/` — agent-managed precedent.
- ADR-019 canonical source split (governance — engine cannot know product identity).

## Out of scope

- Admin UI for curating system-managed blocks (product layer).
- Cross-tenant memory sharing (stronghold concern).
- Memory garbage collection / decay (already covered by ADR-011).
- Replacing existing memory protocols (this extends, does not replace).
- Gate-mediated agent-suggests-admin-approves promotion under `SYSTEM_MANAGED` (follow-up if real demand surfaces).
