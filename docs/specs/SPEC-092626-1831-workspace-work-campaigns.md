---
id: SPEC-092626-1831
title: "Workspace work campaigns narrow eligible work without owning it"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-09-26
history:
  - status: Proposed
    date: 2026-09-26
substrate:
  - maistro-engine#ADR-019
implements:
  - maistro-engine#ADR-092626-c1e7
related:
  - maistro-engine#SPEC-091726-7c2a
  - maistro-engine#ADR-092326-7ed7
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-092626-1831: Workspace work campaigns narrow eligible work without owning it

- **Status:** Proposed
- **Date:** 2026-09-26
- **ADR:** `ADR-092626-c1e7` (Proposed)
- **Issue:** #103 (M3-C6). Parent epic #82. Depends on #98 (BacklogItem) and #100.
- **Consumers:** #804 persistent Workspace Agent (now), #50 RSI (later)
- **Technical Area:** Workspace backlog, operator control plane

## Context

People need to steer ongoing, already-authorized work without rewriting
prompts. They want to narrow the pool the Workspace Agent may pick from, to pin,
pause or exclude items, to set budgets and stop conditions, and to keep their
own priority separate from whatever score the system computes. #103 asks for
this as a generic Workspace contract. RSI (#50) is a later consumer. It is not
the owner of campaign semantics.

Nothing on `develop` defines this today. The only "campaign" code is
marketing DAG seeds and the RSI-private git-notes reconstructor
`read_campaign` in `maistro_rsi.trace_notes`. That reconstructor is the kind of
RSI-owned campaign model #50 says must not become authority. No code defines an
autonomy mode or a pin-next, pause, exclude or human-only control. There is no
selection policy and no policy-version audit.

This spec records the contract before any code, so #103's implementation PRs
have stable AC ids to mark with `@pytest.mark.ac`. It stays `Proposed` until
the open questions below are decided.

## Control flow

```
Campaign / operator policy
        ↓ narrows
eligible BacklogItems / linked Goals
        ↓ chosen by
authorized Workspace Agent / actor
        ↓ claim / activate / reconcile
canonical Goal → Graph → Run
```

## Goals

- Define a **campaign** as operator policy that narrows which BacklogItems and
  linked Goals an actor may choose.
- Define the per-item **autonomy mode** and the durable **operator controls**.
- Keep **explicit human priority** separate from the **system selection
  score's** inputs.
- State the invariants that stop a campaign from widening authorization or
  reassigning a Goal, and the audit key every decision carries.
- Give #804 one contract to consume now, and let #50 reuse it later.

## Non-goals

- **Permissions.** A campaign grants nothing. Authorization stays with the
  existing policy owners (Sentinel, Workspace membership, capability grants).
- **Goal ownership or lifecycle.** A campaign does not own Goals, copy Goal
  ownership into BacklogItem fields, or add a Goal state. The canonical Goal
  stays the only owner. `docs/architecture/INTEROP-ONTOLOGY-v1.md` names
  `maistro.goals` as its semantic owner; that package is not implemented yet.
- **Scheduling or execution.** A campaign is not a scheduler, queue, lease or
  Run lifecycle. The Run lease and fence primitives (`ExecutionLease`,
  `StaleExecutionFence`, `CursorLease`) are unchanged. A campaign filters
  eligibility before any of them are involved.
- **The BacklogItem shape.** #98 owns BacklogItem. A campaign reads an item's
  tags, milestone, package, Workspace/Project scope and linked `goal_id` /
  `goal_revision`, and adds no BacklogItem semantics. Where per-item mode,
  explicit human priority and park state are stored is open (Q4).
- **Multi-tenancy.** Hard tenant isolation stays in the importing product
  (ADR-019). Campaign scope uses the soft Workspace/Project axes only.
- **Deciding the open questions** listed below.

## Decision

### Campaign

A campaign is a versioned operator policy record scoped to a Workspace or to a
Project inside one. Every change creates a new `policy_version`, and earlier
versions are kept. A campaign may:

- **constrain eligibility** by tags, milestones, packages, and Workspace or
  Project scope;
- **set budgets** for cost, time and completion count, each of which acts as a
  stop condition on new selections when reached (what happens to work already
  in progress is open, Q3);
- **name protected areas** (paths, packages or resources). At selection time an
  item whose declared scope includes a protected area is not eligible for
  automated selection. Enforcement once a Run starts stays with the existing
  runtime owners (Sentinel, capability grants); a campaign adds none.

A campaign only ever **removes** items from the eligible set. The eligible set
under a campaign is always a subset of what the actor is already authorized to
choose without it.

### Autonomy modes

Every item under a campaign has exactly one mode, taken verbatim from #103:

| Mode | Meaning |
| --- | --- |
| `autonomous` | The actor may select, claim and complete the item. |
| `autonomous-with-promotion-approval` | The actor may select and do the work; promoting the result needs a human approval. |
| `human-review-required` | The actor may select and prepare the item; a human reviews before it counts as done. |
| `human-only` | The actor must never select or claim the item. |

The default mode for an item with no explicit mode is an open question (below).

### Operator controls

The controls are **pin-next**, **pause**, **exclude** and **human-only**. Each
one is a durable, attributed record, not process memory, and survives a
restart. The UI and API both write the same record. Clearing a control is also
a recorded decision.

- **pin-next**: the pinned eligible item outranks the system score. How it
  orders against explicit human priority and other pins is part of Q1.
- **pause**: the campaign or item is not selected until the pause is cleared.
- **exclude**: the item is removed from the eligible set.
- **human-only**: sets the item's mode to `human-only`. Clearing it returns
  the item to the mode it had before, recorded as its own decision.

### Priority and selection score

Two inputs are kept separate and recorded separately:

1. **Explicit human priority**: set by a person, stored as given, and never
   rewritten by the system.
2. **System selection score**: may consider criticality, unblock value,
   verification confidence, expected learning value, cost, risk and dependency
   readiness.

How the two combine into one order, and whether human priority is a hard
override, a tie-break or a weighted input, is an open question. A selection
decision records both inputs and the rule version that combined them.

### Goal linkage

Eligibility may reference linked canonical Goal state, for example "only items
whose linked Goal is active". It reads that state by `goal_id` and
`goal_revision` and does not copy Goal ownership or lifecycle into BacklogItem
or campaign fields.

### Stalled work

An item that is stalled or blocked may be **parked** with evidence (the reason,
the blocking dependency or failing check, and the Run or artifact references).
Parking removes it from the eligible set until an attributed decision
un-parks it, and another eligible item can be selected in the meantime.
Whether un-parking can also happen automatically when the blocker resolves is
open (Q5). Parking does not change
the linked Goal's state or owner.

### Invariants

1. **No authorization widening.** Selecting, claiming or parking under a
   campaign never gives the actor a permission, capability or scope it did not
   already hold. A campaign that names an item the actor cannot access leaves
   that item ineligible.
2. **No silent Goal reassignment.** Selecting or claiming an item never
   changes the linked Goal's owning Agent. A reassignment remains an explicit
   Goal operation with its own record.
3. **Every decision is audit-keyed.** Each campaign change, eligibility
   decision, selection, control change and park records the actor (user or
   Agent identity) and the `policy_version` it was made under.
4. **Human-only is absolute.** No selection path, including pin-next, returns a
   `human-only` item to an automated actor.

### Consumers

- **#804 persistent Workspace Agent** reads the eligible set and selection
  order from this contract now.
- **#50 RSI** reuses the same contract later. It does not define an
  RSI-private campaign model, and `maistro_rsi.trace_notes.read_campaign`
  stays a trace reconstructor, not a policy authority.

## Acceptance criteria

These mirror #103's acceptance bullets one to one.

<!-- ac-state: unproven AC-1 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->
<!-- ac-state: unproven AC-2 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->
<!-- ac-state: unproven AC-3 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->
<!-- ac-state: unproven AC-4 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->
<!-- ac-state: unproven AC-5 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->
<!-- ac-state: unproven AC-6 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->
<!-- ac-state: unproven AC-7 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->
<!-- ac-state: unproven AC-8 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->
<!-- ac-state: unproven AC-9 - Proposed spec; no implementation yet, owed by #103's implementation PRs -->

```gherkin
Feature: Workspace work campaigns narrow eligible work without owning it

  @AC-1
  Scenario: A campaign constrains scope, budgets and protected areas
    Given a campaign constraining tags, milestones, packages and Workspace or Project scope
    And cost, time and completion budgets and a named protected area
    When eligibility is evaluated
    Then only items inside every constraint are eligible
    And no item whose declared scope includes the protected area is eligible for automated selection
    And no new item is selected once any budget is reached

  @AC-2
  Scenario: Each item carries one autonomy mode
    Given items in autonomous, autonomous-with-promotion-approval, human-review-required and human-only modes
    When an automated actor selects work
    Then each item's mode governs what the actor may do with it
    And a human-only item is never selected or claimed by the actor

  @AC-3
  Scenario: Human priority stays separate from the system score
    Given an item with an explicit human priority
    When the system computes a selection score that may consider criticality, unblock value, verification confidence, expected learning value, cost, risk and dependency readiness
    Then the human priority is stored unchanged
    And the selection record carries both inputs and the combining rule's version

  @AC-4
  Scenario: Eligibility reads linked Goal state without copying it
    Given a campaign whose eligibility references the linked canonical Goal's state
    When eligibility is evaluated
    Then the Goal is read by goal_id and goal_revision
    And no Goal ownership or lifecycle field is written to the BacklogItem or campaign

  @AC-5
  Scenario: Operator controls survive restart
    Given pin-next, pause, exclude and human-only controls set from the UI
    When the process restarts
    Then every control is still in effect with its actor and time

  @AC-6
  Scenario: Stalled work is parked with evidence
    Given a selected item that is stalled or blocked
    When it is parked with evidence
    Then it leaves the eligible set with that evidence recorded
    And another eligible item can be selected

  @AC-7
  Scenario: Selection cannot widen authorization or reassign a Goal
    Given an actor without access to an item a campaign names
    When the actor selects or claims work
    Then that item is not eligible for the actor
    And claiming any item leaves its linked Goal's owner unchanged

  @AC-8
  Scenario: Every decision is attributable
    Given campaign, eligibility, selection and control decisions
    When the audit trail is read
    Then each decision names the actor and the policy version it was made under

  @AC-9
  Scenario: One contract for the Workspace Agent and later RSI
    Given the persistent Workspace Agent under #804
    When it selects work
    Then it consumes this contract
    And no RSI-private campaign model is required for #50 to reuse it
```

## Testing

Implementation PRs for #103 mark their tests `@pytest.mark.ac("AC-n")` against
this spec once it advances past `Proposed`. Durability (AC-5) is tested against
the real store across a restart, and the invariants (AC-7, AC-8) on the shipped
selection path, not on a seam only tests construct. This spec adds no tests.

## Open questions

- **Q1. Priority combination rule.** Is explicit human priority a hard
  override, a tie-break on the system score, or a weighted input to it?
- **Q2. Default autonomy mode.** What mode does an item under a campaign get
  when none is set?
- **Q3. Budgets and overlapping campaigns.** When several campaigns cover one
  item, do their constraints intersect, and how do their budgets combine? When
  a budget is reached, does in-progress or pinned work continue?
- **Q4. Record owner.** Do the campaign record, per-item mode, explicit human
  priority and park state live beside BacklogItem (#98) or in a campaign
  store, given the M1 convergence freeze on new universal owners?
- **Q5. Un-parking.** Is a parked item only returned by a person, or also
  automatically when its recorded blocker clears?

## References

- #103, #82, #98, #100, #804, #50
- [ADR-092626-c1e7](../adr/ADR-092626-c1e7-workspace-work-campaigns-are-narrowing-policy.md):
  the boundary decision this spec implements.
- [ADR-019 canonical source split](../adr/ADR-019-canonical-source-split.md):
  campaigns are product-agnostic engine policy, with hard tenancy left to the
  importing product.
- [INTEROP-ONTOLOGY-v1](../architecture/INTEROP-ONTOLOGY-v1.md): Goal ownership
  (invariant 4), Goal versus Run lifecycle (invariant 5), and consumers adopting
  the canonical Goal rather than defining their own (invariant 15).
- [SPEC-091726-7c2a](SPEC-091726-7c2a-brief-interview-before-goal-commit.md):
  the Workspace Agent's Goal intake, which precedes campaign selection.
