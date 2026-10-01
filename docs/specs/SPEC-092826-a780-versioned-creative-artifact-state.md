---
id: SPEC-092826-a780
title: "Versioned human+AI artifact state, locks, guidance, and branch control"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-09-28
accepted: 2026-09-28
history:
  - status: Proposed
    date: 2026-09-28
  - status: Accepted
    date: 2026-09-28
  - status: AC Defined
    date: 2026-09-28
substrate:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-083026-1cb1
implements:
  - maistro-engine#ADR-083026-e602
related:
  - maistro-engine#SPEC-083026-b2b5
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-design/tests/test_artifact_versions.py
ac-modules:
  AC-1: maistro_design.versions
  AC-2: maistro_design.versions
  AC-3: maistro_design.versions
  AC-4: maistro_design.version_store
  AC-5: maistro_design.versions
  AC-6: maistro_design.version_store
  AC-7: maistro_design.versions
  AC-8: maistro_design.versions
  AC-9: maistro_design.versions
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-092826-a780: Versioned human+AI artifact state, locks, guidance, and branch control

## Context

Issue #780 (M3, child of premier outcome #773). Design Studio needs one durable
artifact/change model so direct editing, AI collaboration, autonomous
generation, and interruption/resumption operate on the same representation,
and autonomous work never erases human edits or accepted versions.

The model is an **extension of the canonical artifact/provenance contract**, not
a competing artifact store: a version embeds the `DesignOutput` content shape
and the canonical Run/NodeRun/Attempt provenance (#709, SPEC-083026-b2b5) —
this spec implements ADR-083026-e602's decision (a record names its producing
execution) for creative artifact versions, the contract SPEC-083026-b2b5
records for learnings/outcomes/design outputs — and branch control is product
state **projected onto** canonical `RunStatus` — never a second lifecycle
(`scripts/check-execution-lifecycles.py` guards this).

Front-matter note: the issue graph (#773 parent; #774/#775/#777/#779 related)
cannot be expressed in registry references, which admit only ADR/SPEC ids; the
issue linkage lives here in prose.

Reconciliation with the issue's dependency line (#774 CreativeBrief, #775
creative DAG, #777 mixed control): at this lane's base none of those stores are
landed. This change therefore records the CreativeBrief as a versioned
*reference identity* (`brief_ref`) and shared decisions as cited
`{decision_ref: digest}` inputs — forward-compatible with #774/#777 — and
expresses dependency-aware invalidation by supersession within the version
lineage. Deep DAG-level invalidation lands with #775 and must consume
`CreativeArtifactService.agent_inputs()`.

## Goals

- Migration 047 adds `design_artifact_versions` (append-only,
  UNIQUE (project_id, lineage_id, version), first-writer-wins),
  `design_artifact_locks`, `design_project_guidance`, and
  `design_branch_controls`.
- `ArtifactVersion` carries: lineage + version, parent version, fork
  relationship, kind (generation/manual_edit/refinement/fork), origin
  (human/agent), producing principal or Run/NodeRun/Attempt (never both
  pretending), `brief_ref`, decision inputs, draft/accepted/rejected state,
  content digest, timestamp.
- `CreativeArtifactService` is the one write path: agent writes require
  canonical run provenance; manual edits require an author principal; both
  append to the same lineage and export through `ArtifactVersion.to_dict()`.
- Locks (version/region/decision/branch) are checked before every write; a
  conflicting change raises `ArtifactLockConflict` naming every lock hit.
  Releasing a lock is an explicit action recording who and when.
- Guidance is durable project input: active guidance reaches newly eligible
  work via `agent_inputs()`; superseded guidance stays readable.
- `BranchStateView` projects control mode + locks + the canonical `RunStatus`
  verbatim (paused/waiting/complete/stopped are canonical states).

## Non-goals

- No Design-Studio-private execution lifecycle: pause/cancel/wait stay
  canonical Run operations; this module stores which Run a branch is attached
  to and reads its status as a projection.
- No CreativeBrief store (#774), no creative DAG (#775), no mixed-control
  orchestration surface (#777). References are recorded; the stores own their
  semantics.
- Region locks require the caller to declare `changed_addresses`; an edit that
  declares nothing cannot prove a locked region untouched and is refused.
- No backfill: artifacts written before versions existed have no version rows.

## Acceptance Criteria

```gherkin
Feature: Versioned human+AI artifact state

  @AC-1
  Scenario: AI generates, a person edits, an agent resumes — all inspectable
    Given an artifact generated inside a canonical Run as lineage v1
    When a person records a manual edit as v2 and an agent records a refinement as v3
    Then all three versions remain inspectable in order with parent links intact
    And v1 and v3 carry their producing Run/NodeRun/Attempt and no author principal
    And v2 carries the human author principal and no run ids

  @AC-2
  Scenario: A locked accepted artifact refuses autonomous replacement
    Given an accepted version locked by a user
    When an autonomous refinement targets that version
    Then the refinement is refused with the lock named
    And an unrelated branch in the same project continues uninterrupted
    And releasing the lock explicitly allows the refinement

  @AC-3
  Scenario: A locked shared decision constrains descendants that reference it
    Given a shared decision locked with a content digest
    When a descendant cites the same decision with the same digest
    Then it is accepted
    When a descendant cites the decision with a different digest
    Then it is refused with the lock named

  @AC-4
  Scenario: Guidance is durable and reaches newly eligible work
    Given guidance recorded during active work
    When the store is closed and reopened as a new process
    Then the guidance is still active and is returned by agent_inputs
    And superseding it keeps the old record readable and inactive

  @AC-5
  Scenario: A fork preserves the original branch
    Given an existing lineage
    When a user forks it into a new lineage
    Then the new lineage starts at the forked content naming its source
    And the source lineage keeps every version and its tip unchanged

  @AC-6
  Scenario: Control and lock state survive a restart and project canonical truth
    Given a branch with a persisted control mode, locks, and an accepted version
    When the store is closed and reopened as a new process
    Then the control mode and locks read back identically
    And the projected view reports paused, awaiting-approval, complete or stopped from the canonical RunStatus verbatim

  @AC-7
  Scenario: Lock conflicts are surfaced, never silent
    Given a branch locked pending review
    When any change attempts to append to it
    Then an ArtifactLockConflict names every lock that blocked it
    And a version left in draft by a refused attempt does not exist

  @AC-8
  Scenario: Manual and AI edits share one representation and export path
    Given one version produced by a person and one produced inside a Run
    When each is exported with to_dict
    Then both carry the same key set and a content digest
    And neither misattributes its producer

  @AC-9
  Scenario: One mixed-control project, three simultaneous branches
    Given one project with a directly-controlled, an autonomous, and a locked branch
    When the direct branch takes a human edit, the autonomous branch refines inside its Run, and the autonomous path attempts the locked branch
    Then the human and autonomous tips advance with correct provenance
    And the locked branch stays at its accepted version with the conflict surfaced
```
