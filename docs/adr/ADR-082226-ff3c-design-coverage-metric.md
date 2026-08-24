---
id: ADR-082226-ff3c
title: "Design coverage: one monotone number for how much of the decided design is proven"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-22
substrate:
  - maistro-engine#ADR-062026-9b30
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082226-ff3c: Design coverage

## Context

Every quality instrument in this repository counts **debt** — things that are
wrong, recorded so they cannot increase. Ten ratcheted counters in
`quality/ac-state-ceilings.json`, a Vulture identity ledger, a reachability
baseline, a convergence matrix.

Nothing counts **distance**: how much of the design the ADRs describe is
implemented and proven. Without that, "every green PR moves us closer to the
designed future state" is an aspiration CI cannot check, because there is no
number that would have to go up. Traceability plus non-regression is necessary
and is not progress — a PR that changes nothing satisfies both.

`scripts/check-ac-state.py` already reports something adjacent, and it is worth
saying why it is not the answer:

```
specs at tier declared  : 26
specs at tier covered   : 0
specs at tier passing   : 2
specs at tier reachable : 3
```

**The `covered: 0` is not a bug.** A spec's tier is the *minimum* rung across
its criteria, and exactly one criterion in the whole corpus sits at `covered`
(a marker whose test did not pass) — inside a spec that also has criteria at
`declared`, so the min pins it to `declared`. Measured at criterion level the
distribution is `declared 211, covered 1, passing 29, reachable 70`.

That min-fold is precisely why the spec tier cannot be the metric: **one
unwritten criterion drags a whole document to the bottom**, and the number
cannot move until the *last* criterion in a spec is finished. A number that
sits still while real work lands is a number people stop reading.

## The measurement that decided the shape

Over the 99 ADRs whose status is `Accepted` or `Implemented`:

| Formulation | Value | What its denominator is |
|---|---:|---|
| criterion-weighted, over ADRs that have criteria | **30.5%** | 348 criteria belonging to 23 ADRs |
| decision-weighted, every taken decision counts | **4.0%** | 99 decisions; 94 of them score zero |

**76 of 99 taken decisions declare no acceptance criteria anywhere** — not in
the ADR, not in any implementing spec.

The first number is the dangerous one. Its denominator is "criteria that
exist", so a decision with nothing written simply vanishes from it, and the
metric reads respectably while three-quarters of the design is unmeasured.
Worse, it is *gameable in the wrong direction*: deleting an unproven criterion
raises it.

## Decision

**Design coverage is decision-weighted.** For each ADR whose status is
`Accepted` or `Implemented`, take the fraction of its criteria — its own, plus
those of every spec whose `implements:` names it — that have reached the
`reachable` rung. A decision that declares no criteria contributes **0**, not
nothing. Design coverage is the mean of those fractions.

Four consequences, all intended:

1. **Every taken decision counts equally.** A one-criterion ADR and a
   forty-criterion ADR are each one unit of design. The alternative weights the
   metric by how verbosely a decision was written.
2. **Writing criteria can only help.** An ADR at 0 with nothing written moves
   the moment one criterion is proven. Deleting every criterion returns it to 0.
3. **`Proposed` is excluded.** A decision not yet taken cannot be owed an
   implementation, and counting it would make writing an idea down look like
   incurring debt.
4. **Accepting an ADR lowers the number.** Newly-owed work is now owed. This is
   correct and it will feel wrong the first time it blocks a PR, which is why
   it is written here rather than discovered there.

The number may rise or hold, never fall, enforced by the same ratchet mechanism
as the debt counters. A deliberate fall — retiring an ADR, discovering a
criterion was never real — is banked with `--bank` and reviewed in the diff.

`reachable` and not `passing` is the bar: a passing test whose module the import
graph cannot reach proves the test runs, not that the system does.

## Consequences

### Positive

- "Closer to the designed future state" becomes a measurement rather than a
  claim, and a PR that changes nothing no longer satisfies it.
- The ADR-change half of the problem falls out of the same number rather than
  needing its own mechanism: an amended or superseded ADR declares criteria with
  no spec, no AC and no test, so coverage drops and the ratchet demands it be
  restored. The decision changing is what creates the obligation.
- The gap between 4.0% and 30.5% is itself the report: it names how much of the
  design has never been written down as anything checkable.

### Negative / Trade-offs

- **The starting number is 4.0%, and it will look bad.** That is the honest
  reading of a corpus where 94 of 99 taken decisions have nothing proven. A
  metric chosen to flatter would not be worth ratcheting.
- Movement is slow near the floor: proving one criterion of a forty-criterion
  ADR moves the mean by 0.025 points. The counter is coarse at this end, and the
  ratchet's "may not fall" is doing most of the work until the corpus catches up.
- It says nothing about whether the ADRs describe a *good* system. Traceability
  to a bad decision is still traceability.
- A criterion can be tautological and still reach `reachable`. This measures
  that evidence exists, never that it is meaningful — which is why an approving
  human review stays in the merge path.

### Neutral

- The existing per-spec tier counters stay as a report. They answer a different
  question (which documents are wholly finished) and the min-fold is right for
  that.
- Publication lives in `docs/architecture/CONVERGENCE-MATRIX.md`, which already
  carries per-subsystem convergence rows and is already machine-checked.
