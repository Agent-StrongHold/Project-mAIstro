---
id: SPEC-092926-7a02
title: "Closed-loop design-process contract: Goal, Rubric, Pack, Fence, eval-on-Run"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-09-29
history:
  - status: Proposed
    date: 2026-09-29
substrate:
  - maistro-engine#ADR-036
  - maistro-engine#ADR-097
implements:
  - maistro-engine#ADR-092926-7a01
related:
  - maistro-engine#ADR-060
  - maistro-engine#ADR-061
  - maistro-engine#SPEC-092926-7a01
  - maistro-engine#SPEC-093026-7a90
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/fitness/test_canonical_loop_kind_authority.py::test_no_competing_loop_kind_registration
  - packages/maistro-core/tests/fitness/test_canonical_loop_kind_authority.py::test_fence_detects_a_synthetic_competing_registration
ac-modules:
  AC-1: maistro.ontology.registry
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-092926-7a02: Closed-loop design-process contract: Goal, Rubric, Pack, Fence, eval-on-Run

- **Status:** Proposed
- **Date:** 2026-09-29
- **ADR:** `ADR-092926-7a01` (Proposed)
- **Issue:** #790 (M7-A1). Initiative #788; parent epic #789; milestone #787.

## Context

Issue #790 asks for "an ADR/spec that names Goal, Rubric, Pack, Fence, and
eval-on-Run, and forbids a second product/runtime/eval authority." The ADR
makes the authority decision; this spec fixes the enforceable wording of that
decision — the reserved vocabulary, the boundaries each wave must build
inside, and the CI evidence that already proves the boundary holds — so the
M7 waves (#791–#796) inherit one contract instead of re-negotiating it.

This is not a third contract: `SPEC-092926-7a01` is the ADR-anchored
kind-fencing decision this spec enforces, and `SPEC-093026-7a90` records the
wave-level control flow and acceptance-criterion ids (#791–#796) that consume
this boundary.

## Contract objects

| Object | Kind | Owner | Boundary |
|---|---|---|---|
| Goal | canonical ontology kind (#458) | `maistro.goals` | Rubric binds to a Goal revision; M7 never re-owns Goal |
| Rubric | Goal scored-acceptance ontology kind, registered in `maistro.ontology` (#791's `rubric.py`) | `maistro.goals` | distinct from persona RubricEval (ADR-060) and CreativeBrief (#774) |
| Pack | Graph/skill pack of one Run (#793) | graph/skills | not a package, route, or product identity |
| Fence | decision on a waiting NodeRun (#794) | runs lifecycle (ADR-097) | extends #48/#737 pause machinery; no new pause universe |
| eval-on-Run | evidence on Run/NodeRun/Attempt (#792) | runs records | no side store, client cache, or product verdict table |

## Reserved vocabulary

The loop-kind namespace is reserved to `packages/maistro-core/src/maistro/ontology/`:

- reserved slugs (case-insensitive): `goal`, `goals`, `rubric`, `rubrics`,
  `run`, `runs`, `eval`, `evals`, `evaluation`, `evaluations`;
- a `register(<reserved-slug>, ...)` call anywhere else in production Python
  is a competing loop identity and fails CI;
- `DesignRun`, `EvalRun`, and `VariantStore` are forbidden execution-lifecycle
  names everywhere in production code (frozen by #990).

`Pack` and `Fence` are deliberately *not* reserved slugs: they are loop
contracts, not ontology kinds.

## Enforcement map

| Boundary | Enforcement | Evidence |
|---|---|---|
| runtime kind namespace | `test_canonical_loop_kind_authority.py` fence | passes on `develop`; synthetic `Goal` registration trips it |
| product shapes (app identity, routes, client storage, egress, animation) | `test_no_second_design_product.py` (#990) | 13 guards, negative-control validated |
| lifecycle vocabulary | `scripts/check-execution-lifecycles.py` | Run/NodeRun/Attempt is the one execution lifecycle |

## Acceptance criteria

- **AC-1** (namespace): production Python outside the canonical ontology
  module registers no reserved loop-kind slug. Evidence: the fence test.
- **AC-2** (one lifecycle): no competing execution-lifecycle identity exists
  in production code. Evidence: the #990 lifecycle-name guard.
  <!-- ac-state: unproven AC-2 - covered and passing in this change
  (test_no_second_design_product.py::test_no_competing_execution_lifecycle_name);
  the lifecycle vocabulary is a tree-wide property with no single owning module
  to anchor, so the `reachable` rung waits for #791/#793 to bind it to the
  runs records -->
- **AC-3** (distinct kinds): Goal-level Rubric, persona RubricEval
  (`maistro.personas.rubric`, ADR-060), and CreativeBrief (#774) remain
  distinct kinds with distinct owners. Evidence: wave issues #791/#774 carry
  the behavioral proof; this spec only pins the distinction.
  <!-- ac-state: unproven AC-3 - the behavioral proof is wave work (#791 Rubric
  ontology kind, #774 CreativeBrief); this spec pins the distinction only -->
- **AC-4** (no second authority): Evolve/RSI (#796) and the M4 promotion
  loop (#21) consume eval-on-Run evidence; neither evaluates inside the Run.
  Evidence: lands with #796's mapping.
  <!-- ac-state: unproven AC-4 - the consumer mapping is #796's deliverable;
  no in-Run evaluator exists to forbid yet -->

Wave gates B and C (eval-on-Run visibility, restart-safe fences, shared Run
identity across packs, public proof lineage) are the *wave issues'* acceptance
(#791–#796) and are out of scope here; this spec carries only the authority
boundary they must respect.
