---
id: ADR-070
title: "The Repertoire Pattern — reuse-first cascade (perform, improvise, rehearse, compose)"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-30
substrate: []
implements: []
related:
  - maistro-engine#ADR-007
  - maistro-engine#ADR-017
  - maistro-engine#ADR-032
  - maistro-engine#ADR-051
  - maistro-engine#ADR-068
  - maistro-engine#ADR-069
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
  - status: Implemented
  - status: Accepted
    date: 2026-08-25
    reason: "M0 strict evidence reconciliation: current acceptance evidence does not support an Implemented completion claim; implementation history remains recorded."

---

# ADR-070: The Repertoire Pattern

> **Convergence note (2026-08-19).** This ADR is marked `Implemented`, but the
> code implementing it has no path from any process entry point — see
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363). That
> is not an oversight:
> [SPEC-258](../specs/SPEC-258-repertoire-pattern-core.md) built the generic
> `Repertoire` protocol and `repertoire_run` cascade, and put refactoring the
> existing instances — Builders' `SpecTemplateStore`, the Router's selector,
> RLPHD — in Non-goals. This ADR's own acceptance criterion 6 asks only that
> they be *documented* as conforming, not migrated. The machinery has no
> callers because the migration that would call it was explicitly deferred.
>
> The status is knowingly left unchanged rather than corrected. The capability
> is still wanted, so `Deprecated` would be false; `Superseded` requires a
> `superseded-by` and nothing replaces this. Both are terminal, so choosing
> wrong forecloses the other, and ADR-097's forward-only lifecycle offers no
> transition back from `Implemented` for an ADR marked so optimistically.
> Correcting it truthfully needs either the missing substrate or a lifecycle
> that can express "specified, partially built, blocked".


**Status:** Proposed
**Date:** 2026-05-30

---

## Context

The same shape keeps reappearing across subsystems: *reuse a verified prior solution for a
similar input; if none fits (or the stakes are high), reason from scratch; verify before
committing; then store the verified result so the next similar input is cheap.* It exists,
half-built and un-named, in at least six places:

| Subsystem | "reuse" | "reason" | "store back" |
|-----------|---------|----------|--------------|
| Builders (Quartermaster) | matched spec template | LLM spec authoring | verified spec → template (`SpecTemplateStore`) |
| Router (ADR-007) | best known variant | Thompson exploration | update posterior |
| RLPHD (ADR-068) | predict from history | ask the human | update predictor + θ |
| Memory / learnings | retrieve learning | reason from scratch | store new learning |
| Skills / Forge | reuse a skill | Forge a new one | canary → promote |
| Planner (ADR-071) | matched plan template | MCTS / Tree-of-Thoughts | verified plan → template |

Naming it once, as a first-class pattern, lets these share a mental model, a protocol, and the
same correctness invariants — and lets new subsystems adopt it deliberately instead of
re-deriving it. The payoff is structural: **cost-per-input trends down as the library grows,
while quality trends up**, because every expensive success is distilled into a cheap, verified,
reusable artifact.

## Decision

Adopt the **Repertoire Pattern** — a reuse-first cascade in four movements. The maistro/maestro
vocabulary names the movements; the parenthetical is the engineering beat.

1. **Perform** *(recall)* — Retrieve a **verified entry** from the Repertoire whose *class* matches
   the input; adapt and use it. This is the default, cheap path. Most inputs never leave it.
2. **Improvise** *(reason / search)* — On a Repertoire **miss**, or when the input is **high-stakes**
   (impact/novelty above a threshold), search the solution space — guided by the nearest
   Repertoire entries as **priors**, not from a blank slate.
3. **Rehearse** *(verify)* — Before committing, **verify** the candidate against checkable criteria
   (contracts/invariants per ADR-032, property tests, or a domain verifier). **Nothing is performed
   or stored unverified.**
4. **Compose** *(refine / distill)* — On a **verified success**, distill the result into a **new
   signed Repertoire entry** (ADR-069) keyed by input class, so the next similar input hits
   *Perform*. `maistro-evolve` mutates/crosses entries to improve the Repertoire over time
   (FunSearch-style verifier-gated evolution).

### The Repertoire (the library)

A **versioned, signed library of verified entries** keyed by input class:

- **Source of truth in the DB**, online-editable under RBAC, exported to human-readable YAML/JSON
  for backup (the engine config model). Entries (and the learned value/selector weights) live here.
- **Entries are signed** (ADR-069); the Repertoire is a code/template-execution surface, so a
  poisoned entry is a supply-chain attack (the engine's primary threat anchor). Entries are
  therefore **verifier-gated on entry** (only *Rehearse*-passing results compose) and **signed**,
  and untrusted-code entries execute in a microVM (ADR-069).
- **Demotion/eviction:** outcome feedback (ADR-017) demotes entries whose real-world success
  regresses; the Repertoire is monotone in *verified* entries but not immortal.

### Perform-vs-Improvise gate (explore/exploit)

A learned value/selector decides when a recalled entry is good enough to *Perform* vs when to
*Improvise*. This is the **same machinery already shipped**: ADR-007 Thompson sampling and the
ADR-068 RLPHD confidence threshold are instances of this gate. Confidence + stakes set the
threshold; high-stakes inputs bias toward *Improvise* + human *Rehearse*.

### Invariants of the pattern

- **Reuse-first** — always attempt *Perform* before *Improvise* (cost discipline).
- **Verify-always** — nothing commits or enters the Repertoire without *Rehearse*.
- **Monotone improvement** — *Compose* only adds verified entries; bad entries are demoted by
  outcome feedback, never silently retained.
- **Honest cost curve** — novel inputs stay expensive (correct); the win is that *recurring*
  inputs cheapen as the Repertoire fills. No silent quality loss to save cost.

## Interface (sketch)

A generic protocol any subsystem can implement (`I` = input, `S` = solution, `E` = entry):

```python
class Repertoire(Protocol):
    def recall(self, input_class: str) -> Entry | None: ...                 # Perform
    def improvise(self, inp: Input, priors: list[Entry]) -> Solution: ...   # Improvise
    def rehearse(self, candidate: Solution) -> Verdict: ...                 # Rehearse (verify)
    def compose(self, verified: Solution, input_class: str) -> Entry: ...   # Compose (distill)

async def repertoire_run(rep: Repertoire, inp: Input, *, stakes: float) -> Solution:
    entry = rep.recall(class_of(inp))
    if entry and gate_perform(entry, stakes):          # explore/exploit (ADR-007 / ADR-068)
        return adapt(entry, inp)
    candidate = rep.improvise(inp, priors=rep.nearest(class_of(inp)))
    verdict = rep.rehearse(candidate)                  # verify before commit (ADR-032)
    if not verdict.ok:
        raise RehearsalFailed(verdict)
    rep.compose(candidate, class_of(inp))              # distill → signed entry (ADR-069)
    return candidate
```

## Acceptance criteria

- [ ] A subsystem implementing `Repertoire` attempts `recall` before `improvise` (reuse-first;
      property test: a known-class input with a passing entry never calls `improvise`).
- [ ] No solution is committed or composed without a passing `rehearse` (verify-always).
- [ ] `compose` writes a **signed** entry (ADR-069); an unsigned/invalid entry is never recalled.
- [ ] The Perform-vs-Improvise gate is the ADR-007 / ADR-068 selector, not a new bespoke one.
- [ ] Outcome regression (ADR-017) demotes an entry; demoted entries stop being recalled.
- [ ] Existing instances (Builders `SpecTemplateStore`, `VariantSelector`, RLPHD) are documented
      as conforming instances (or a follow-up tracks aligning them).

## Consequences

- One mental model + one protocol for "get cheaper and smarter over time" across the system.
- `maistro-evolve` is named precisely: it is the **Compose** stage's improvement engine.
- New subsystems (the ADR-071 planner first) implement `Repertoire` rather than re-deriving it.
- Existing subsystems (Builders, Router, RLPHD) become *instances* — reframing, not rewriting.

## Out of scope

- The specific search algorithm used in *Improvise* per subsystem (e.g. MCTS for the planner,
  Thompson for the router) — chosen by the applying ADR.
- The verifier bodies used in *Rehearse* (domain-specific).
- The learned value-function training mechanics (per-subsystem follow-up SPECs; e.g. RLPHD's).
