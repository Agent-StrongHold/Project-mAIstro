---
id: ADR-082526-0d30
title: "CI runner cost is measured per PR head, in job-minutes, not estimated over a time window"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_measure_ci_cost.py
ac-modules:
  AC-1: '@tool/measure-ci-cost'
  AC-2: '@tool/measure-ci-cost'
  AC-3: '@tool/measure-ci-cost'
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-0d30: CI runner cost is measured per PR head, in job-minutes, not estimated over a time window

## Context

#161 removed the `branches:` filter from four workflows. Those filters matched
on the PR's **base**, so a PR stacked on a feature branch ran none of them —
Registry CI and Formal Conformance only, out of twenty-five checks. The work was
not unreviewed; it was unmeasured, and every accumulated failure arrived at once
on retarget.

The implementing PR shipped that change and satisfied three of #161's four
acceptance bullets. The fourth — *runner cost is measured before and after,
with the deliberate exclusions named* — was **reasoned about rather than
measured**, and the PR said so, expecting the first runs after merge to supply
the number. No measurement was ever recorded, and the acceptance audit reopened
the issue on exactly that.

The obvious way to supply it is to compare total CI minutes for the week before
the merge against the week after. That number would be dominated by how many PRs
happened to be open each week, not by the change — a measurement whose error bar
is larger than the effect it claims to size.

## Decision

Measure one PR head, and read both sides off it.

The change altered **which PRs trigger a workflow**, not what any workflow does.
The old trigger set is therefore a strict subset of the new one, and both costs
are present in a single head's job list: the "before" cost of a stacked PR is
the subset that carried no base filter, and the "after" cost is the whole set.
No time window, no PR-volume confound, and the two figures come from the same
run so nothing drifts between them.

`UNFILTERED_BEFORE` names that subset — `registry.yml` and
`formal-conformance.yml` — rather than deriving it. Derivation would read the
workflows *as they are now*, which no longer carry the filters #161 removed, so
the "before" set would silently become everything and the measured delta would
be zero. The bug would report the change as free.

**Job-minutes, not billable minutes.** GitHub reports `total_ms: 0` for this
repository, so a cost stated in money is zero and says nothing about the
constraint that is real: contention for concurrent runners, and how long a
contributor waits. Wall-clock is reported alongside but separately, because
parallelism puts the two far apart — 36.3 job-minutes complete in under seven.

**What is deliberately not measured:** what `concurrency: cancel-in-progress`
saves. Every one of these workflows sets it for pull-request events, so a
superseded push stops paying — but that saving is a function of how often people
push, not of one head. Claiming a number for it from a single run would be
precisely the reasoned-about-not-measured figure that reopened #161.

## Acceptance criteria

- [x] **AC-1** The before, after and marginal figures are computed from one
  head's job list, with `marginal` the difference of the other two.
- [x] **AC-2** A job whose timestamps run backwards — a skipped job does —
  contributes zero rather than a negative summand.
- [x] **AC-3** The set of workflows a stacked PR ran before the change is named,
  not derived from the current workflow triggers.

## Consequences

### Positive
- #161's last acceptance bullet is answered with a number that can be
  regenerated, rather than an argument.
- The measurement tool is itself tested. An unverified measurement tool would
  reproduce the defect that reopened #161 one level down.

### Negative / Trade-offs
- A single head is one sample. Job durations vary with runner luck and cache
  state, so the figure is an order of magnitude, not a constant — which is what
  a cost decision needs, and the script re-runs on demand for a fresh one.
- `UNFILTERED_BEFORE` is a historical fact hard-coded in a script. It is correct
  and will stay correct because it describes a past state, but it will read as
  arbitrary to anyone who does not follow the reference to #161.

### Neutral
- The deliberate exclusions were already named and machine-checked in
  `docs/ci/REQUIRED-CHECKS.md`; this records the cost, not the exclusions.
