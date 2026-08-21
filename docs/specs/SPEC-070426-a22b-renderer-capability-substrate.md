---
id: SPEC-070426-a22b
title: "Renderer capability substrate — slots, providers, discovery, graceful absence"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-07-04
substrate:
  - maistro-engine#ADR-061
implements:
  - maistro-engine#ADR-070426-f2a0
related:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-188
  - maistro-engine#ADR-038
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-design/tests/test_renderers.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070426-a22b: Renderer capability substrate

## Context

ADR-070426-f2a0 decided that external renderers are optional capability providers and
that a skill whose renderer is absent must be silently filtered out (no error), while a
discovered-but-failing renderer is a real fault. This SPEC defines the provider-agnostic
substrate that realizes that: the slot model, the `RenderProvider` protocol, discovery,
the skill-availability filter, and the absence-vs-failure split. It is the core that
SPEC-070426-6ea8 (Open Design) and SPEC-070426-457b (canvas exporters) both implement.

## Goals

- Define renderer capability **slots** and register providers into `maistro.capabilities`.
- Define a `RenderProvider` protocol: `slots`, `discover()`, `render(prompt_stack) -> ArtifactNode`.
- Add `DesignSkillRegistry.list_available(filled_slots)` so absent-slot skills are never offered.
- Wire discovery + periodic re-probe through the self-repair governor (SPEC-188).
- Separate **absence** (silent filter) from **failure** (circuit-break via ADR-038).

## Non-goals

- Any concrete provider implementation (see SPEC-070426-6ea8, SPEC-070426-457b).
- Changing the `DesignEngine` prompt-stack boundary (ADR-061 stays intact).
- A UI for browsing available renderers.

## Decision

### Slots
Register renderer slots as capability slots: `renderer.fixed-page`, `renderer.deck`,
`renderer.reflowable-web`, `renderer.video`, `designsystems.live`. `renderer.fixed-page`
is filled unconditionally by the canvas floor.

### RenderProvider protocol (sketch)
```python
class RenderProvider(Protocol):
    slots: tuple[str, ...]
    async def discover(self) -> DiscoveryResult: ...      # never raises; up(slots) | down()
    async def render(self, prompt_stack: PromptStack,
                     skill: DesignSkill) -> ArtifactNode: ...  # may raise -> resilience
```

### Availability filter
```python
def list_available(self, filled_slots: set[str]) -> list[DesignSkill]:
    return [s for s in self.list_featured() if s.required_renderer in filled_slots]
```
`renderer.fixed-page` is always in `filled_slots`, so canvas-native skills are never filtered.

### Absence vs failure
- `discover()` → `down()` (not installed / unreachable): slot unfilled → skill filtered → silent.
- `render()` raises on a discovered provider: circuit-break the provider (ADR-038), empty its
  slots until recovery, surface the error to the caller who invoked that render — never crash the pipeline.

### Discovery lifecycle
Probe on registry build; the self-repair governor (SPEC-188) re-probes on an interval so a
provider that starts later lights its slots up without a restart, and one that dies removes them.

## Acceptance criteria

- With no providers registered, `list_available` returns exactly the canvas-native (fixed-page) skills; no errors.
- Registering a provider whose `discover()` returns `up({slot})` makes that slot's skills appear.
- A provider whose `discover()` returns `down()` never causes its skills to be offered.
- A `render()` exception trips the circuit breaker and empties the provider's slots without raising past the caller.

## Testing

- Unit: slot registry, `list_available` filter, discover-up/down transitions (mock providers).
- Unit: circuit-breaker trip on `render()` failure re-empties slots; recovery re-fills.
- Integration: self-repair re-probe flips availability as a mock daemon toggles.

## Open questions

- Should `designsystems.live` be a renderer slot or a separate capability category?
- Do multiple providers for one slot compose (fallback chain) or is it first-wins?

## References

- ADR-070426-f2a0 — the deciding ADR.
- SPEC-184 modular capability platform; SPEC-188 self-repair loop.
- ADR-038 reliability taxonomy.
