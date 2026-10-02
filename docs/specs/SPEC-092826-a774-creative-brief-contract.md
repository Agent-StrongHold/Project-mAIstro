---
id: SPEC-092826-a774
title: CreativeBrief is a versioned Design Studio projection of one canonical Goal revision
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-09-28
accepted: 2026-09-28
owners:
  - '@BlakeMatthews-dev'
layer: Foundation
history:
  - status: Proposed
    date: 2026-09-28
  - status: Accepted
    date: 2026-09-28
  - status: AC Defined
    date: 2026-09-28
substrate:
  - maistro-engine#ADR-032
  - maistro-engine#ADR-036
  - maistro-engine#ADR-091726-7c2a
  - maistro-engine#ADR-091626-ba4f
  - maistro-engine#ADR-092326-7ed7
implements:
  - maistro-engine#ADR-036
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-design/tests/test_creative_brief.py
  - packages/maistro-design/tests/test_creative_brief_store.py
  - packages/maistro-design/tests/test_creative_brief_pg.py
ac-modules:
  AC-1: 'maistro_design.brief'
  AC-2: 'maistro_design.brief'
  AC-3: 'maistro_design.brief'
  AC-4: 'maistro_design.brief'
  AC-5: 'maistro_design.brief'
  AC-6: 'maistro_design.brief'
  AC-7: 'maistro_design.brief'
  AC-8: 'maistro_design.brief'
  AC-9: 'maistro_design.brief'
  AC-10: 'maistro_design.brief'
  AC-11: 'maistro_design.brief_store'
  AC-12: 'maistro_design.brief'
  AC-13: 'maistro_design.brief'
  AC-14: 'maistro_design.brief'
---

# SPEC-092826-a774: CreativeBrief is a versioned Design Studio projection of one canonical Goal revision

## Problem

Unified Creative Production (#773) needs one versioned creative-context
object that every artifact branch can consume. The hazard the issue (#774)
guards against is structural: Design Studio drifting into owning Goal
identity, Persona identity, delegation, or authorization — each of which has
exactly one canonical owner (`maistro.interop` / #458, ADR-092326-7ed7,
#39, ADR-091626-ba4f).

## Decision

`packages/maistro-design/src/maistro_design/brief.py` owns one frozen
`CreativeBrief` model; `brief_store.py` owns its persistence contract
(`PgCreativeBriefStore`, table `design_creative_briefs`, migration 049 — renumbered from 047 after develop claimed the id).

### Boundary contracts

- **Projection, not replacement.** Every brief records `workspace_id`,
  `project_id`, `goal_id`, `goal_revision` (exact revision consumed),
  `goal_owner_agent_id`, and an optional delegation/subgoal reference. The
  reference set is validated against `INTEROP_ONTOLOGY_V1`
  (`Workspace -> Project -> Goal`). Design Studio mints no Goal, no
  ownership, no delegation authority.
- **References, not copies.** Persona and Design System are `BriefReference`
  values (identity + version). Changing either creates a new brief version
  for future work; historical artifacts keep what they consumed.
- **Immutable by version.** Briefs are frozen; identity is
  `(lineage_id, version)` with `brief_id` naming the exact version. Updates
  go through `new_version()`, which mints identity/provenance itself and can
  never move the lineage to another Workspace/Project. The store is
  append-only: insert and reads, no update.
- **Structural scope rejection.** Any reference carrying a `workspace_id`
  that differs from the brief's is rejected at construction
  (`CrossWorkspaceReferenceError`); the store additionally refuses a Project
  not registered to the claimed Workspace in `canonical_projects`, and the
  column carries an FK to `canonical_projects` (RESTRICT).
- **Derived projections carry source identity.** `project(request_id)`
  builds an `ArtifactProjection` copying Goal revision, brief
  lineage/version, Persona and Design System identity verbatim. Overrides
  are explicit and explained (`ProjectionOverride.field/reason`), and the
  protected shared-context fields (`PROTECTED_PROJECTION_FIELDS`) raise
  `ProtectedFieldOverrideError` — shared changes are a new brief version.
- **No authorization surface.** The models forbid extra fields, the field
  vocabulary contains no grants/capabilities/bindings/approvals, and
  supervision constraints are recorded annotations — never a second
  delegation or authorization authority.
- **Source truth is referenced.** `RequiredFact` carries `EvidenceReference`
  pointers; the brief constrains claims (`prohibited_claims`) and never
  stores generated ones.

### Redirect semantics

A changed desired Project outcome is a new canonical Goal revision (committed
outside Design Studio) consumed by a *new* brief version
(`new_version(goal_id=..., goal_revision=...)`). Creative-execution-only
guidance changes are a new brief version against the same Goal revision.
Neither erases nor rewrites prior versions; newly eligible work consumes
`latest(lineage_id)` (dependency-aware invalidation is #775's; locks are
#780's).

## Acceptance criteria

- **AC-1** one model + one persistence contract own CreativeBrief domain
  state; the store satisfies `CreativeBriefStore`.
- **AC-2** every brief references one canonical Goal identity + exact
  revision.
- **AC-3** Goal ownership/delegation remain canonical references; no brief
  path mutates scope or ownership.
- **AC-4** Persona and Design System are versioned references, not copies.
- **AC-5** creative-context updates mint versions; prior versions and the
  projections derived from them stay byte-identical.
- **AC-6** a changed outcome is a new Goal revision + new brief version,
  without history rewrite.
- **AC-7** projections expose the exact Goal + brief + Persona + Design
  System versions consumed.
- **AC-8** projections retain source versions; overrides are explicit,
  explained, and rejected on protected context.
- **AC-9** required facts carry evidence references; prohibited claims are a
  distinct field; no generated-claims store exists.
- **AC-10** supervision constraints are annotations with no authority.
- **AC-11** cross-Workspace references are structurally rejected (model and
  store).
- **AC-12** two artifact branches receive `shared_context()`-identical
  context, differing only in explicit request/overrides.
- **AC-13** redirects produce versioned state with untouched provenance.
- **AC-14** no brief field grants authorization or bypasses
  Capability/Binding policy (`extra='forbid'` + vocabulary guard).

Each criterion is claimed by `@pytest.mark.ac("SPEC-092826-a774/AC-N")` on
the tests in `test_creative_brief.py` (domain model) and
`test_creative_brief_store.py` (persistence guards).
