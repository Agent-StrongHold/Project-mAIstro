---
id: ADR-088
title: "maistro-evolve — experimental genome optimiser"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate:
  - maistro-engine#ADR-070
implements: []
related:
  - maistro-engine#ADR-007
  - maistro-engine#ADR-017
  - maistro-engine#ADR-075
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-088: maistro-evolve — experimental genome optimiser

**Status:** Proposed
**Date:** 2026-05-30
**Records the intended shape** of the maistro-evolve package while stating plainly that it is
EXPERIMENTAL — no stability contract yet, and this ADR will be revised once it settles.

---

## Context

`maistro-evolve` (the Elo tournament / genome optimiser package) exists and has a test suite, but its
architecture has never been written down and is still moving. Downstream code should not assume its
interfaces are stable. This ADR pins the *intended* design so the direction is legible, while marking
the package experimental so nothing builds a hard dependency on its current shape.

## Decision

**maistro-evolve is EXPERIMENTAL.** It has **no stability contract** and is explicitly subject to
change. No other package should depend on its API surface as if it were locked.

Its **intended-but-not-locked** shape:

- A **genome** is a recipe / prompt variant — the unit that gets composed, mutated, and selected.
- **Fitness comes from the outcome store (ADR-017)** — variants are scored by their recorded
  outcomes, not by a bespoke metric.
- **Winners are promoted one-way** into the recipe registry **via canary** (ADR-007). Promotion is a
  forward-only registry write through the canary path; it **does not auto-write memory**.

Architecturally, maistro-evolve is the **"Compose / Refine" engine of the Repertoire pattern
(ADR-070)** — it generates and refines candidate genomes that the Repertoire flow then rehearses and
admits. It also **drives the auto-advancement of release channels** in universal versioning
(ADR-075): a winning, canaried genome advances its channel.

Because the package is experimental, this ADR is a **direction record, not a contract**. It **will be
revised once maistro-evolve stabilises**, at which point a stability contract can be stated.

## Acceptance criteria

- [ ] The ADR states explicitly that maistro-evolve is experimental, has no stability contract, and
      is subject to change.
- [ ] A genome is defined as a recipe / prompt variant.
- [ ] Fitness is sourced from the outcome store (ADR-017), not a separate scoring path.
- [ ] Winner promotion is one-way into the recipe registry via canary (ADR-007) and does not
      auto-write memory.
- [ ] The package is identified as the Compose / Refine engine of the Repertoire pattern (ADR-070)
      and as the driver of release-channel auto-advancement in universal versioning (ADR-075).
- [ ] The ADR commits to being revised once the package stabilises.

## Consequences

- The intended architecture of maistro-evolve is legible without implying it is frozen.
- Downstream code is warned off depending on the current API; the experimental label is explicit.
- A clear revision trigger (stabilisation) is on record, so this ADR is not mistaken for a final
  contract.

## Out of scope

- The concrete genome encoding, crossover / mutation operators, and tournament parameters.
- The fitness formula details beyond "sourced from the ADR-017 outcome store."
- Any stability / backward-compatibility guarantee — deferred until the package stabilises.
