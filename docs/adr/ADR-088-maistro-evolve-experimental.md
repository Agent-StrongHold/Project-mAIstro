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

## Operational contract: canonical Evolve cycle recovery (#1064)

The experimental package remains Evolve's owner of population and tournament
semantics; this does not create a second execution lifecycle. For a cycle run
through Hive Conductor, the canonical Graph/Run/NodeRun/Attempt records remain
the sole execution authority. Evolve's domain state is a reconstructible
projection associated with those records, not an alternate scheduler or run
store.

The Conductor-owned durable domain store persists versioned Evolve snapshots
(population genomes, cycle markers, tournament ratings and battle history,
frozen membership, and the battle-journal position) and publication evidence.
The package owns the serialization contract through
`maistro_evolve.durable_snapshot.export_domain_state` and
`restore_domain_state`; replicas restore the snapshot and replay only journal
entries after its recorded position. Battle and finalize publications are
identified by canonical Run/NodeRun identity. Finalization persists its
committed domain snapshot before its committed marker; a missing or faulted
marker is not success. If an interrupted mutation cannot safely be retried
from the restored pre-cycle snapshot, recovery fails closed with an explicit
reconciliation disposition rather than silently replaying or claiming success.

Admission snapshots provide the compensation base for incomplete cycles.
Recovery reconstructs node implementations from durable Run facts through the
shipped resolver, and uses the canonical execution lease/fence and the
service's cycle lock to prevent overlapping publication. A fresh cycle has a
new canonical identity and therefore does not inherit an earlier cycle's
publication keys. These rules describe the Conductor integration; they do not
turn the experimental package API into a general stability guarantee.

## Consequences

- The intended architecture of maistro-evolve is legible without implying it is frozen.
- Downstream code is warned off depending on the current API; the experimental label is explicit.
- A clear revision trigger (stabilisation) is on record, so this ADR is not mistaken for a final
  contract.

## Out of scope

- The concrete genome encoding, crossover / mutation operators, and tournament parameters.
- The fitness formula details beyond "sourced from the ADR-017 outcome store."
- Any stability / backward-compatibility guarantee — deferred until the package stabilises.
