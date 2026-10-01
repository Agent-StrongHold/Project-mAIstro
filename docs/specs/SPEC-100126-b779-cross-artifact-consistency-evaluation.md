---
id: SPEC-100126-b779
title: "Cross-artifact consistency evaluation and targeted refinement"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-10-01
accepted: 2026-10-01
history:
  - status: Proposed
    date: 2026-10-01
  - status: Accepted
    date: 2026-10-01
  - status: AC Defined
    date: 2026-10-01
substrate:
  - maistro-engine#ADR-061
  - maistro-engine#ADR-032
implements:
  - maistro-engine#ADR-061
related:
  - maistro-engine#ADR-093026-7a90
  - maistro-engine#SPEC-091726-7c2a
  - maistro-engine#ADR-092926-7a01
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-design/tests/test_consistency.py
  - packages/hive-conductor/backend/tests/test_design_consistency_route.py
source:
  - packages/maistro-design/src/maistro_design/consistency.py
  - packages/maistro-design/src/maistro_design/nodes.py
  - packages/hive-conductor/backend/routes/design.py
ac-modules:
  AC-1: maistro_design.consistency
  AC-2: maistro_design.consistency
  AC-3: maistro_design.consistency
  AC-4: maistro_design.consistency
  AC-5: maistro_design.consistency
  AC-6: maistro_design.consistency
  AC-7: maistro_design.consistency
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-100126-b779: Cross-artifact consistency evaluation and targeted refinement

Issue #779 (M3 slice of Unified Creative Production, parent #773). One explicit
way to judge whether a family of artifacts still represents the same goal,
Persona, Design System and source truth, then route only the affected work for
refinement. This is project-quality evaluation, not a self-improvement
authority: the evaluator may propose work, while the canonical DAG/Run logic
decides what actually runs under current user locks, control mode and
authority (`maistro_design.consistency`, executed as the `design.consistency_eval`
node inside a canonical Run, and surfaced for inspection through
`POST /v1/design/projects/{id}/consistency`). It implements the accepted
maistro-design package charter (ADR-061); the canonical-pipeline eval decision
it follows — evaluation on the Run, refinement as a later Attempt, no sidecar
eval identity — is recorded in ADR-093026-7a90 (still Proposed, so cited as
related rather than governing authority).

## Scope

In bounds: the deterministic evaluator, its canonical graph node, the Design
Studio inspection route, and their tests.

Out of bounds (the issue's stop condition): no second promotion/evolution
system — historical evaluations may later become evidence for M4 governed
improvement, but this slice only evaluates and refines the current creative
project. The browser E2E harness is tracked separately (see AC-8).

## Acceptance criteria

- [x] **AC-1** A planted Persona violation in one artifact is detected and only that affected branch is proposed for refinement — impact comes from real graph relationships (`references` closure), never hard-coded artifact-type rules.
- [x] **AC-2** A planted shared factual contradiction identifies all descendants that consumed the bad shared decision, walking `consumes` edges plus transitive `references`.
- [x] **AC-3** A locked accepted artifact is reported as conflicting when necessary but is not silently rewritten: it is a refinement target carrying `requires_unlock`, and the evaluation is a read-only proposal over a frozen snapshot.
- [x] **AC-4** The evaluator cites the exact brief version, goal revision, per-decision and per-artifact versions it evaluated, so results remain interpretable after later edits (same snapshot in, same interpretable verdict out).
- [x] **AC-5** Factual/claim evaluation distinguishes provided evidence from model-generated assertions: evidence-backed claims pass, assertions are flagged as a distinct, weaker verdict, and the claim-rule shape is validator-enforced.
- [x] **AC-6** Cross-artifact evaluation is inspectable from the Design Studio project and carries canonical Run provenance: the inspection route runs the same pure evaluator over the submitted snapshot, refuses a snapshot naming a foreign project, and the node's results are stored under the Run's own project.
- [x] **AC-7** Retrying/refining creates normal Run/NodeRun/Attempt evidence and preserves the failed evaluation record.
- [ ] **AC-8** Browser E2E demonstrates one inconsistent sibling being corrected while unrelated accepted siblings remain unchanged.

  <!-- ac-state: unproven AC-8 - needs the workspace UI browser-E2E harness, which is a separate tracked slice; the evaluator-level and route-level behavior it will demonstrate is proven by AC-1..AC-7 above -->

## Evaluation dimensions

The evaluator scores, at minimum: persona/voice consistency; design-system
compliance; factual and allowed-claim consistency against source/evidence
(distinguishing provided evidence from model-generated assertions); audience
and objective alignment; terminology/name consistency; required message/CTA
coverage; contradictions between sibling artifacts; channel-specific
requirements; accessibility constraints appropriate to the artifact type; and
locked user decisions that must not be violated.

The result contract identifies which brief/decision/artifact versions were
evaluated, which dimensions passed/failed, the evidence for each finding, the
affected artifact/decision nodes, whether the defect is local to one branch or
originates in shared upstream context, and a recommended refinement target —
without silently changing the project.
