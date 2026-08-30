---
id: SPEC-082926-c2d7
title: An ac-modules anchor must name a module the reachability graph knows
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
  - status: AC Defined
    date: 2026-08-29
substrate:
  - maistro-engine#ADR-082226-ff3c
implements:
  - maistro-engine#ADR-082226-ff3c
related:
  - maistro-engine#ADR-082926-25a2
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_ac_state_anchor_resolution.py
source:
  - scripts/check_ac_state_impl.py
ac-modules:
  AC-1: '@tool/check_ac_state_impl'
  AC-2: '@tool/check_ac_state_impl'
  AC-3: '@tool/check_ac_state_impl'
  AC-4: '@tool/check_ac_state_impl'
  AC-5: '@tool/check_ac_state_impl'
  AC-6: '@tool/check_ac_state_impl'
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-c2d7: An ac-modules anchor must name a module the reachability graph knows

## Context

The AC ladder's top rung, `reachable`, is the one that asks whether anything
actually runs the code a criterion is about. It decided by asking whether the
criterion's `ac-modules` anchor is in the *unreachable* set:

```python
return not any(".".join(parts[: i + 1]) in unreachable for i in range(len(parts)))
```

Membership in that set is the whole test, so **absence reads as reachable** —
and a name the graph has never heard of is absent from it. A typo, a module
named without its scope, a script filename, an invented string and the empty
string all cleared the rung built to catch exactly this.

`design_coverage` is derived from those rungs, and the ratchet enforces it as a
**floor**. So an unresolvable anchor does not merely mislabel one criterion: it
raises the number the merge button is trusted against.

A survey of the corpus found **32 of 263 anchors (12%) across five specs**
naming nothing:

| spelling | example | what it should have been |
|---|---|---|
| script filename | `check-convergence-matrix` | `@tool/check-convergence-matrix` |
| app module, unscoped | `routes.settings` | `@flat/hive-conductor/routes.settings` |
| tooling module, unscoped | `ac_state_notes` | `@tool/ac_state_notes` |
| package module, unscoped | `contained_validation` | `maistro_rsi.contained_validation` |

## Decision

Anchors are resolved against the reachability graph's own module universe
before anything is counted, and an anchor that resolves to nothing fails the
gate.

The universe is loaded from `check-reachability.py` rather than re-derived, so
the names an anchor is checked against are the names the rung is judged on. A
second walk of the tree would be a second definition of "module", and the two
would drift precisely where it mattered.

**The two failures stay apart.** "This anchor names nothing" is a corpus error
and fails. "This module is real but nothing imports it" is the finding the rung
was built for, and still reports `passing`. Collapsing them would hide the
second inside the first — three anchors in the corpus are of the second kind
and must keep reporting exactly as they did.

An anchor of `None` is *unannotated*, a state the rung already handles by
stopping at `passing`. The empty string is not that: it is an anchor someone
wrote and left blank, and it is reported.

## Measured effect

**Correcting all 32 anchors moved `design_coverage` by zero** — 26.6798% before
and after. Every one of them named a module that is in fact reachable, so the
inflation this closes was, in this corpus, nil.

That is worth stating plainly rather than implying a recovered number. What the
change buys is not a corrected measurement today but a measurement that cannot
be wrong tomorrow: before it, nothing distinguished the 32 anchors that happened
to point at reachable code from an anchor pointing at nothing at all, and the
floor would have absorbed either.

## Both document kinds, not just specs (#653)

The first version of this gate walked `specs` alone. ADRs carry `ac-modules`
too, and `design_coverage` folds an ADR's **own** criteria in beside its specs'
— `rungs = [c["rung"] for c in adr["own_detail"]]` runs before any spec tier is
considered. So an ADR anchor was graded on the same ladder, raised the same
floor, and was read by nothing: **49 of 279 (18%)** named no module, in the same
four spellings the specs had.

The walk now covers both, through `_criteria_of`, because the two kinds hold
their criteria under different keys — `criteria` for a spec, `own_detail` for an
ADR. Every place that has to remember which key a document uses is a place one
of them gets forgotten, which is exactly how half the corpus went unchecked.

`_report_unresolvable_anchors` takes the ADRs as a **required** parameter. A
default would let the next caller reintroduce the omission silently, and the
omission is the whole defect.

Correcting all 49 moved `design_coverage` by zero, for the same reason the
original 32 did: every one named a module that is in fact reachable. Stated
plainly rather than implying a recovered number — what changes is that a rename
orphaning an ADR anchor now fails instead of raising the floor.

## Consequences

### Positive
- The floor the ratchet enforces is made of criteria that resolve.
- A rename that orphans an anchor fails loudly instead of raising coverage.
- The error names the three identity shapes, so the fix does not need this spec.

### Negative / Trade-offs
- Anchors must be spelled with their scope, which is longer and less obvious
  than the bare module name. The error message carries an example of each shape
  for that reason.
- The gate imports `check-reachability.py`, coupling two scripts. Deriving the
  universe separately was the alternative and is worse: it is how the two
  definitions of "module" would diverge.

### Neutral
- No change to how `reachable` is computed for anchors that do resolve.

## Acceptance Criteria

```gherkin
Feature: An ac-modules anchor must name a module the reachability graph knows

  @AC-1
  Scenario: The universe is the reachability graph's own
    Given the module universe the anchor check resolves against
    When it is loaded
    Then it holds package, flat-app and tooling identities alike

  @AC-2
  Scenario: An anchor naming nothing is reported
    Given a criterion anchored to a name no module has
    When the anchors are checked
    Then that criterion is reported as unresolvable

  @AC-2
  Scenario: A blank anchor is reported, an absent one is not
    Given one criterion anchored to the empty string and one with no anchor
    When the anchors are checked
    Then the blank one is reported
    And the criterion with no anchor is not

  @AC-2
  Scenario: A gate that cannot load the graph reports nothing
    Given the module universe could not be loaded
    When the anchors are checked
    Then nothing is reported, rather than every anchor

  @AC-3
  Scenario: A real but unwired module is not an unresolvable anchor
    Given a criterion anchored to a module the graph knows and nothing imports
    When the anchors are checked
    Then it is not reported as unresolvable
    And the rung still declines to call it reachable

  @AC-4
  Scenario: An ADR anchor naming nothing is reported
    Given an ADR criterion anchored to a name no module has
    When the anchors are checked
    Then that criterion is reported as unresolvable
    And the report names the document kind, the file, the criterion and the string

  @AC-4
  Scenario: The gate cannot be called for specs alone
    Given the report is asked to walk a corpus
    When it is called
    Then it requires the ADRs as well as the specs

  @AC-5
  Scenario: Every anchor in the corpus resolves, of either kind
    Given the specs and the ADRs as they stand
    When their anchors are checked
    Then nothing is reported

  @AC-6
  Scenario: Widening the walk leaves spec verdicts unchanged
    Given a spec anchored to a name no module has and an ADR corpus that is clean
    When the anchors are checked
    Then the spec is reported exactly as it was before ADRs were walked

  @AC-6
  Scenario: A real but unwired module in an ADR is not an unresolvable anchor
    Given an ADR criterion anchored to a module the graph knows and nothing imports
    When the anchors are checked
    Then it is not reported as unresolvable
```
