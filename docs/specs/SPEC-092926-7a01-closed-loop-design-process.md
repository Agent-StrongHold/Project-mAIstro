---
id: SPEC-092926-7a01
title: "Closed-loop design process — M7 kind-fencing contract"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-09-29
substrate:
  - maistro-engine#ADR-092926-7a01
  - maistro-engine#ADR-036
  - maistro-engine#ADR-081226-a66b
implements:
  - maistro-engine#ADR-092926-7a01
related:
  - maistro-engine#ADR-060
  - maistro-engine#ADR-061
  - maistro-engine#ADR-091726-7c2a
  - maistro-engine#SPEC-091726-7c2a
  - maistro-engine#ADR-095
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#ADR-092926-7a01
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/ontology/test_design_loop_kind_fencing.py
source:
  - packages/maistro-core/tests/ontology/test_design_loop_kind_fencing.py
layer: Orchestration
ac-modules:
  AC-1: maistro.ontology.registry
  AC-2: maistro.interop.contract
  AC-3: maistro.interop.contract
  AC-4: maistro.interop.contract
  AC-5: maistro.ontology.registry
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-09-29
---

# SPEC-092926-7a01: Closed-loop design process — M7 kind-fencing contract

M7-A1 contract lane (#790, parent #789). This spec is the testable face of
ADR-092926-7a01: it pins the design-loop kind table to machine-checked guards so
a later M7 lane cannot quietly grow a competing Goal, a sidecar eval identity, or
a persona-owned scoring kind. The A2–A7 lanes are blocked-by the ADR; this spec
ships only the fencing evidence.

## Scope

In bounds: ontology/interop contract tests under
`packages/maistro-core/tests/ontology/`, the ADR/spec pair, and doc pointers.

Out of bounds (the ADR's stop condition): Rubric persistence, eval wiring,
packs, fence runtime, any UI, and every file under `packages/maistro-canvas/**`.

## Acceptance Criteria

Each criterion below is covered by a passing named test in this change (see
Validation), but the top `reachable` rung additionally requires its anchor
module — `maistro.ontology.registry` or `maistro.interop.contract` — to be
reachable from a production entry point. Both modules are library handoff
contracts banked unreachable in `quality/reachability-baseline.json` (pending
the explicit production-entrypoint connection work, #373); they become
reachable only when the M7 runtime lanes (A2–A7) wire them. Each marker below
is retired by the wiring PR that connects its anchor module:

<!-- ac-state: unproven AC-1 - covered and passing in this change (packages/maistro-core/tests/ontology/test_design_loop_kind_fencing.py); the `reachable` rung needs `maistro.ontology.registry` reachable from a production entry point — the module is banked unreachable in quality/reachability-baseline.json pending the production-entrypoint connection work (#373) -->

The M7 design-loop kinds (`Goal`, `Rubric`, and the reserved-forbidden sidecar
name `EvalRun`) are fenced to the ontology registry: an `InMemoryOntology` that
already holds a kind's canonical semantics rejects a product module's competing
registration of that kind with `KindAlreadyRegisteredError`, while the canonical
owner's same-model re-registration stays idempotent. **AC-1**

<!-- ac-state: unproven AC-2 - covered and passing in this change; the `reachable` rung needs `maistro.interop.contract` reachable from a production entry point — banked unreachable pending the production-entrypoint connection work (#373) -->

The shared ontology declares exactly one Goal identity: `Goal` owned by
`maistro.goals` with identity `goal_id`; no other concept may claim the
`goal_id` identity (no alias can mint a second Goal). **AC-2**

<!-- ac-state: unproven AC-3 - covered and passing in this change; the `reachable` rung needs `maistro.interop.contract` reachable from a production entry point — banked unreachable pending the production-entrypoint connection work (#373) -->

A Goal projection must carry the canonical identity and the exact
`goal_revision`; `validate_projection` rejects projections that carry a foreign
identity (a brief-local DTO cannot project Goal semantics) or omit the revision
(no silent history rewrite — the consumed revision stays recoverable). **AC-3**

<!-- ac-state: unproven AC-4 - covered and passing in this change; the `reachable` rung needs `maistro.interop.contract` reachable from a production entry point — banked unreachable pending the production-entrypoint connection work (#373) -->

Persona scoring is not Goal scoring: `maistro.personas` owns no scoring kind in
the shared ontology, no `RubricEval` concept exists in it, and the persona
`RubricEval` class cannot be registered as the Goal-acceptance `Rubric` kind.
**AC-4**

<!-- ac-state: unproven AC-5 - covered and passing in this change; the `reachable` rung needs `maistro.interop.contract` reachable from a production entry point — banked unreachable pending the production-entrypoint connection work (#373) -->

No sidecar eval identity exists at the contract level: the shared ontology
declares no `EvalRun` concept, and eval evidence is keyed by the producing
Run/NodeRun/Attempt per the ADR. **AC-5**

## Validation

`uv run pytest packages/maistro-core/tests/ontology/test_design_loop_kind_fencing.py`
must pass, and each AC above must keep a named test. The ADR/spec front-matter
chain is gated by registry CI (`maistro_registry.cli lint . --strict`,
`tools/lint_lifecycle.py`, `scripts/check-adr-index.py`).

Until an M7 runtime lane wires `maistro.ontology` / `maistro.interop` into a
production entry point, each AC carries an `ac-state: unproven` marker above
(declared with that reason, per `scripts/check-ac-state.py`): the fence tests
are green, but the `reachable` rung cannot honestly clear while the anchor
modules are banked library handoffs (#373). The wiring PR retires the marker
for the module it connects.

## Implementation notes for A2–A7

- A2 registers the real `Rubric` semantics with the ontology under the
  Goal-acceptance owner named in the ADR kind table and extends
  `maistro.interop` (and `quality/shared-interop-ontology-v1.json`, which must
  stay serialization-identical) with the M7 concepts — the fencing tests then
  run against real canonical models instead of the stand-ins defined in the
  test module.
- A4 extends the producing-run evidence rule (ADR-090226-9c3f precedent) to
  EvalRecords; AC-5's no-sidecar invariant is its guardrail.
- A5 implements FenceDecision persistence on waiting NodeRuns (#48); the three
  redirect targets and the no-rewrite rule are the ADR's, not this spec's, to
  re-litigate.
