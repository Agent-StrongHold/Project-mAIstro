---
id: SPEC-282
title: maistro-automaton — portable autonomous-actor machinery
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-09-21
history:
  - status: Proposed
    date: 2026-09-21
substrate:
  - maistro-engine#ADR-081426-fb9f
implements:
  - maistro-engine#ADR-081426-fb9f
related:
  - maistro-engine#SPEC-081226-034b
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-automaton/tests
source:
  - packages/maistro-automaton
---

# SPEC-282: maistro-automaton — portable autonomous-actor machinery

## Context

The merge train stalls on a repeating pattern, and the pattern is
architectural: the pipeline has sensors (poke, stall-alarm), organs
(enqueue, repair lanes), and even a cage (check scripts), but no actor —
nothing holds state between ticks, remembers refusals, or acts because
internal pressure crossed a threshold rather than because a human typed.
Turing already contains the machinery for exactly this: self-model × mood →
drives (`compute_drives`), threshold-gated producers, a tickable reactor,
episodic memory, and a deterministic cage. But Turing cannot be imported to
get it: ADR-081426-fb9f forbids Turing becoming a peer platform, and
activation-by-dependency would smuggle the cognitive runtime in through a
package import.

The internal conflict — "how do we make Turing importable" — resolves by
rejecting its premise. Turing is not a library to import; it is an
*instantiation* of a library that did not yet exist.

## Decision

Extract the machinery into `maistro-automaton`: a dependency-free package
sitting at the bottom of the graph, exporting six contracts and importing
nothing platform-owned.

1. **Reactor / TickReactor** — the pulse. Handlers see a monotonic tick
   count; interval triggers are named and idempotent-registerable. Explicit
   ticks make every automaton replayable: same ticks, same transitions, same
   verdicts.
2. **DriveSpec / DriveTerm / compute_drives** — drive pressure as declared
   weighted sums over slow facets (normalized) and fast mood attributes,
   clamped to a ceiling. Missing facets contribute zero; missing mood
   attributes raise `MoodContractError` — a mood contract that silently
   loses fields is a mood contract that lies.
3. **Producer / ThresholdGate** — threshold-gated candidate generators.
   Silence is the default posture; a gate is the inspectable statement of
   what it takes to break it.
4. **MotivationArbiter** — at most one action per tick, highest drive wins,
   **per-key refractory periods**. The refractory is the anti-churn
   mechanism: without it, refused pressure resubmits every tick forever
   (eighteen enqueues against one wedge). With it, refusal scars the key
   for a host-sized cooldown.
5. **Episode / EpisodeSink** — the persistence port. The machinery never
   stores; it emits Episodes and the host decides what durability means.
6. **CageCheckpoint / CageVerdict / first_block** — deterministic gates
   returning structured verdicts with enumerated reason codes, never
   raising. Raw exception text is not a reason code; it is an archaeology
   project.

### Instances, not platform

- `maistro_turing` consumes the library; its self-model, persona, producers
  and prompts are content. ADR-081426-fb9f's gate is untouched — Turing
  stays off while its bones are the library.
- The merge-train tender is the first activated instantiation: bounded
  domain, deterministic cage, no self-identity, no persistence ownership.
  Per the ADR's own activation review surface, this is the pilot that
  hardens the machinery in production without waking the mind.
- Dependency direction (SPEC-081226-034b): the library imports nothing
  platform-owned; hosts inject persistence, providers, and law through the
  protocols. Neither the canonical platform nor Turing owns the other.

### Non-goals

No identity, no self-model, no LLM calls, no wall-clock scheduling, no
network, no persistence implementation, no autonomous cognition. An
automaton is a puppet with excellent reflexes; the Real Boy question —
whether and when any instantiation becomes a persistent actor with its own
cognition — is exactly the class of decision that stays behind an
activation gate (ADR-081426-fb9f), per instantiation.

## Acceptance criteria

1. `maistro-automaton` declares zero runtime dependencies and imports
   nothing outside the standard library.
2. All public surface is exercised by the package suite, which is
   deterministic (injected clocks, explicit ticks) and registered in the
   suite inventory with its delta note.
3. `maistro_turing` remains green and unchanged in behavior; its refactor
   onto the library is a follow-up mechanical import-swap, not this spec.
4. The first consumer (merge-train tender) ships caged: enqueue/
   update-branch/comment capabilities only, owner-gated surfaces denied,
   fail-closed when policy infrastructure is unavailable.
