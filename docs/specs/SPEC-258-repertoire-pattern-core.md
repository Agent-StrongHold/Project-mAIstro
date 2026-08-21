---
id: SPEC-258
title: "The Repertoire Pattern — reuse-first cascade protocol and orchestration core (ADR-070)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate:
  - maistro-engine#SPEC-257
related:
  - maistro-engine#ADR-007
  - maistro-engine#ADR-017
  - maistro-engine#ADR-032
  - maistro-engine#ADR-051
  - maistro-engine#ADR-068
  - maistro-engine#ADR-069
implements:
  - maistro-engine#ADR-070
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/repertoire/test_repertoire.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-258: The Repertoire Pattern — reuse-first cascade protocol and orchestration core

## Context

ADR-070 names a reuse-first cascade (perform/improvise/rehearse/compose) that already exists,
half-built and un-named, across Builders, Router, RLPHD, memory, and Skills. This SPEC implements
the generic `Repertoire` protocol and the `repertoire_run` orchestration function the ADR sketches,
plus the perform-vs-improvise gate as an injected selector — so the cascade's invariants
(reuse-first, verify-always, monotone improvement) are enforced once, centrally, and testable
without any specific subsystem's recall/improvise/rehearse logic. Existing instances (Builders'
`SpecTemplateStore`, the Router's Thompson selector, RLPHD) are not refactored to conform in this
SPEC — see Non-goals — this SPEC only builds the core machinery they would conform to.

## Goals

- Add `maistro/repertoire/types.py`: `Verdict` (frozen dataclass: `ok: bool`, `reason: str = ""`),
  `RehearsalFailed` (exception, carries the `Verdict`), `PerformGate` (`Protocol`:
  `should_perform(entry: Any, *, stakes: float) -> bool` — the explore/exploit decision; a
  subsystem supplies its own ADR-007/ADR-068 selector as the concrete implementation).
- Add `maistro/repertoire/protocol.py`: `Repertoire[I, S, E]` (`Protocol`, generic over Input,
  Solution, Entry types):
  - `recall(input_class: str) -> E | None` — Perform: best verified entry for the class, or `None`
    on a miss.
  - `nearest(input_class: str) -> tuple[E, ...]` — entries to use as Improvise priors.
  - `improvise(inp: I, priors: tuple[E, ...]) -> S` — Improvise: reason from scratch, guided by
    priors.
  - `rehearse(candidate: S) -> Verdict` — Rehearse: verify before committing.
  - `compose(verified: S, input_class: str) -> E` — Compose: distill a verified solution into a
    new entry (signed, per ADR-069/SPEC-257 — signing itself is the caller's `compose`
    implementation, not this protocol's concern).
  - `class_of(inp: I) -> str` — maps an input to its Repertoire class key.
- Add `maistro/repertoire/run.py`: `async def repertoire_run(rep: Repertoire[I, S, E], inp: I, *,
  stakes: float, gate: PerformGate) -> S` implementing the cascade exactly as ADR-070 sketches it:
  1. `entry = rep.recall(rep.class_of(inp))`.
  2. If `entry is not None` and `gate.should_perform(entry, stakes=stakes)`: return the performed
     result (this SPEC returns `entry` itself cast as the adapted solution — adaptation logic
     between entry-shape and solution-shape is subsystem-specific and out of scope; see Non-goals
     for the exact boundary).
  3. Otherwise: `candidate = rep.improvise(inp, priors=rep.nearest(rep.class_of(inp)))`.
  4. `verdict = rep.rehearse(candidate)`; if not `verdict.ok`, raise `RehearsalFailed(verdict)` —
     nothing is composed or returned on a failed rehearsal.
  5. `rep.compose(candidate, rep.class_of(inp))`; return `candidate`.

## Non-goals

- Refactoring Builders' `SpecTemplateStore`, the Router's `VariantSelector`, or RLPHD to literally
  implement this `Repertoire` protocol — ADR-070's acceptance criterion 6 only requires they be
  *documented* as conforming instances or tracked for follow-up alignment; this SPEC builds the
  protocol they would implement, not the migration itself.
- The `adapt(entry, inp)` step ADR-070's interface sketch shows between `recall` and returning a
  solution — adaptation is subsystem-specific (e.g. binding a matched spec template's placeholders
  to the actual input) and has no generic pure form; `repertoire_run` here returns the recalled
  entry directly as `S`, leaving subsystem-specific adaptation to a wrapper the consuming
  subsystem writes around this core.
- Outcome-feedback demotion (ADR-017) of Repertoire entries — that's `maistro.memory`'s outcome
  store integration, a follow-up once a concrete `Repertoire` implementation persists entries.
  This SPEC's `Repertoire` protocol has no `demote()` method yet; adding it is a follow-up once a
  real store exists to demote against.
- Persistence / signing of composed entries — `compose()`'s body (DB write, ADR-069 signing) is
  entirely the implementing subsystem's concern; this SPEC only calls `compose()` and uses its
  return value.
- The specific Improvise search algorithm (MCTS, Thompson sampling, RLPHD) — ADR-070 explicitly
  leaves this per-subsystem.
- `maistro-evolve`'s role as the Compose-stage improvement engine — already exists as its own
  package; no integration work here.

## Decision

```python
# maistro/repertoire/types.py
@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""

class RehearsalFailed(Exception):
    def __init__(self, verdict: Verdict) -> None: ...

class PerformGate(Protocol):
    def should_perform(self, entry: Any, *, stakes: float) -> bool: ...

# maistro/repertoire/protocol.py
class Repertoire(Protocol[I, S, E]):
    def recall(self, input_class: str) -> E | None: ...
    def nearest(self, input_class: str) -> tuple[E, ...]: ...
    def improvise(self, inp: I, priors: tuple[E, ...]) -> S: ...
    def rehearse(self, candidate: S) -> Verdict: ...
    def compose(self, verified: S, input_class: str) -> E: ...
    def class_of(self, inp: I) -> str: ...

# maistro/repertoire/run.py
async def repertoire_run(
    rep: Repertoire[I, S, E], inp: I, *, stakes: float, gate: PerformGate
) -> S: ...
```

## Acceptance criteria

- [x] A known-class input with a recallable entry that the gate approves never calls `improvise`
      (reuse-first; property test over a range of `stakes` values where the gate is a simple
      threshold).
- [x] A Repertoire miss (`recall` returns `None`) always calls `improvise`, never raises.
- [x] A gate that rejects the recalled entry (e.g. high stakes) falls through to `improvise` even
      though `recall` had a hit.
- [x] A failing `rehearse` (`Verdict(ok=False, ...)`) raises `RehearsalFailed` carrying that
      verdict, and `compose` is never called (verify-always).
- [x] A passing `rehearse` calls `compose` exactly once with the candidate and the input's class,
      and `repertoire_run` returns the candidate.
- [x] `repertoire_run` never calls both `recall`-path-return and `improvise` for the same input
      (mutually exclusive branches).

## Testing

- `packages/maistro-core/tests/repertoire/test_repertoire.py` (new) — a fake in-memory
  `Repertoire` implementation (no real subsystem wiring) driving the full cascade: reuse-first hit,
  miss-falls-to-improvise, high-stakes-gate-falls-to-improvise, rehearsal-failure short-circuit,
  successful compose-and-return, plus a Hypothesis property test over gate thresholds confirming
  `improvise` is called if and only if `recall` missed or the gate rejected.

## Open questions

- Whether `PerformGate.should_perform` should receive the full candidate-vs-entry comparison
  context (e.g. a similarity score) rather than just `entry` and `stakes` — deferred until a real
  ADR-007/ADR-068 selector is wired in as a concrete `PerformGate`; this SPEC's signature is the
  minimal shape ADR-070's sketch implies.

## References

- [ADR-070: The Repertoire Pattern](../adr/ADR-070-repertoire-pattern.md)
- [ADR-069: Code Registry](../adr/ADR-069-code-registry.md)
- [SPEC-257: Code registry resolve core](SPEC-257-code-registry-resolve-core.md)
