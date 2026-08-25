---
id: ADR-082526-aef8
title: "Repo tooling gets a reachability graph, so a gate's evidence can reach the top rung"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate:
  - maistro-engine#ADR-082526-1899
implements: []
related:
  - maistro-engine#ADR-082226-ff3c
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/test_check_reachability.py
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-aef8: Repo tooling gets a reachability graph

## Context

`check-ac-state.py`'s ladder tops out at `reachable`, and that rung asks one
question: is the module carrying the evidence in the import graph
`check-reachability.py` walks? That graph covers `packages/*/src` and
`packages/*/backend`. A CI gate lives in `scripts/`, so its criteria cap at
`passing` however well tested they are.

Two consequences, both live:

- **The mandate cannot be satisfied.** `mandate_violations` exempts a criterion
  only at `rung == "reachable"`, so every criterion a gate's ADR declares is a
  violation on the PR that creates it.
- **`design_coverage` counts the decision as zero**, because it sums criteria at
  `reachable` only. Accepting a fully-tested gate ADR therefore *lowers* the
  metric by the full dilution of one decision: measured on #248, 9.5371 →
  9.4463 for an ADR with six criteria and nineteen passing tests.

That leaves a gate author two moves, both false in some direction: leave the
ADR `Proposed` after shipping the decision — the defect #239 exists for, and
what `ADR-082226-ff3c` does today — or declare tested criteria `unproven`,
which is what `ADR-082526-1899` did, in the open, as a stopgap.

The instrument that measures whether decisions are proven cannot measure its
own kind of decision.

### What the alternatives cost

Measured against `develop` at `56864e8`:

| Candidate | Consequence |
|---|---|
| Extend the reachability graph to `scripts/` | 43 scripts, 26 rooted at a workflow step, **16 unreached** |
| Add an `enforced` rung beside `reachable` | no measurement change; one more term in a ladder whose value is that it is short |
| Drop tooling ADRs from `design_coverage`'s denominator | lets a decision vanish from its own denominator — the move ADR-082226-ff3c explicitly rejected when it chose decisions over criteria |

Sixteen is a reviewable ledger, and the composition is the argument for doing
this at all rather than a cost to be tolerated:

- **9** are the mutation family (`mutation_*`, `check_mutation_baseline`). They
  are unreached because `.github/workflows/mutation.yml` is a stub whose only
  step prints "Mutation temporarily disabled". A whole quality pillar is off
  and nine scripts are dead behind it, which nothing currently reports.
- **7** are simulations and one-off tooling (`rlphd_*`, `openrouter_rpm_pacer`,
  `generate_repo_tasks*`, `check_assertion_quality`).

## Decision

Extend `check-reachability.py` with a second root set: **scripts a CI workflow
step executes**. Tooling modules join the same ratcheted baseline as production
modules, and a gate's `ac-modules` annotation can then name its own module
truthfully — the module is in a reachability graph, rooted at the workflow step
that runs it.

Roots are discovered from `.github/workflows/*.yml` rather than declared in a
list. A declaration would drift the moment someone renames a step, and the
workflow file is already the authority on what CI runs.

Dynamic loads are resolved the way the package walk already resolves them.
`scripts/ac_outcome_plugin.py` is reached only as the string
`"ac_outcome_plugin"` inside `check-ac-state.py`, never imported — an AST walk
that missed it would report a live pytest plugin as dead, which is the wrong
verdict in the direction that matters.

### What this deliberately does not do

- **It does not re-enable mutation testing.** It reports that nine scripts are
  unreached because the workflow is disabled, with that as their disposition.
  Turning the pillar back on is its own issue with its own evidence.
- **It does not retire the simulations.** Finding them is this decision;
  removing any of them is separate, on the standard #133/#225 parity terms.

## Consequences

### Positive
- A gate's ADR can be `Accepted` with criteria at `reachable`, so shipping a
  gate stops costing `design_coverage` and stops requiring an escape hatch.
- `ADR-082526-1899`'s six `ac-state: unproven` declarations can be retired for
  the real annotation, and `ADR-082226-ff3c` can take the status its own
  shipped decision earned.
- A gate script no workflow runs becomes reportable, which nothing checked
  before.

### Negative / Trade-offs
- Root discovery reads workflow YAML as text. A script invoked through a
  variable, or from a shell script the workflow calls, is not seen — the same
  class of blind spot the package walk's eager-sweep recogniser exists for, and
  it errs toward reporting unreachable rather than toward silence.
- The baseline grows by 16 entries that were previously invisible. They are not
  new debt; they are debt that was never counted.

### Neutral
- The mutation family's disposition will change when `mutation.yml` is
  restored, which is the ledger doing its job rather than churn.

## Acceptance criteria

- [x] **AC-1** A script a workflow step executes is reachable.
- [x] **AC-2** A script no workflow step executes, and that nothing reached
  imports, is reported as unreachable.
- [x] **AC-3** A script reached only through a dynamic string load is
  reachable, not reported.
- [x] **AC-4** A script reached only by an import from another reached script
  is reachable.
- [x] **AC-5** Tooling entries ratchet against the same reviewed baseline as
  production modules, in both directions.
- [x] **AC-6** A criterion whose `ac-modules` names a workflow-rooted tooling
  module reaches the `reachable` rung.
