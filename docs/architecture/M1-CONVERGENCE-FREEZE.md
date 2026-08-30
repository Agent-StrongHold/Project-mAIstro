# M1 Convergence Freeze

**Owner:** #460  
**Policy data:** `quality/m1-convergence-freeze.json`

M1 is a convergence milestone. Until Gates A-E are complete, adding another universal owner is a regression even when the new module is locally well designed.

## Default rule

Do not add a new universal work lifecycle, Run identity, traversal authority, model/tool effect path, approval/recovery authority, shared cross-product type family, or execution-authoritative event bus during M1.

New product behavior must enter the Accepted architecture:

- execution truth: `Run → NodeRun → Attempt → ExecutionRuntime`
- traversal truth: `GraphExecutionState` attached to Run
- governed effects: `Capability → Provider → Binding → Invocation`
- shared cross-product semantics: the versioned ontology owned by #458

Domain-specific state remains allowed. A renderer may own render state; a collaboration feature may own edit-session state; a scheduler may own trigger/cursor state. What it may not do is turn that domain state into another general-purpose execution authority.

## One vocabulary, not another scanner

The freeze composes the architecture-fitness controls established by #36 rather than defining competing meanings for the same concepts:

- `scripts/check-execution-lifecycles.py` remains the authority for work-state lifecycle detection and classification;
- `scripts/check-model-egress.py` plus the direct-effect inventory remain the authority for new model/effect bypasses;
- `packages/maistro-core/tests/fitness/test_import_boundaries.py` remains the authority for core/application direction and compatibility-owner aliases;
- `quality/shared-interop-ontology-v1.json` remains the canonical owner map for cross-product concepts.

`check-m1-convergence-freeze.py` adds only the gap those controls do not cover: a PR can define a new canonical-looking `WorkspaceStore`, `EventSequence`, `RunStore`, `CheckpointStore`, or similar authority inside an already-known subsystem without adding a new matrix row or a work-state enum. The checker compares new top-level class definitions with the candidate's immutable base and rejects those shared-owner-shaped additions outside their canonical owner packages.

Existing convergence debt is not recharged merely because its file changes. The check is new-definition based. A canonical owner may extend its own concept normally.

## Product-local projections

A product may need a DTO, receipt, cache, view, or projection whose name contains a canonical concept. That object is allowed only when it is explicitly non-authoritative. Put this marker in the owning class docstring:

```text
M1 product-local projection: Run
```

Replace `Run` with the canonical concept from the ontology. The marker is not an escape hatch for a second lifecycle or effect path: the existing lifecycle and egress gates still apply independently.

## PR rule

A PR that introduces a new package, service, or shared-owner-shaped type whose responsibility could own execution lifecycle, traversal, scope, events, governed effects, approvals, recovery, or cross-product semantics must either:

1. extend the existing canonical owner; or
2. remain an explicitly product-local projection/adapter/provider; or
3. carry the `m1-convergence-exception` label **and** provide a complete reviewed exception plan.

The label alone authorizes nothing. The PR body must contain non-empty values for all four fields:

```text
Architecture rationale: <why the canonical owner cannot represent the requirement>
Canonical owner: <which canonical authority remains authoritative and how this relates to it>
Disposition owner: <named issue/team/person responsible for convergence or retirement>
Retirement/convergence path: <the concrete condition and path that removes or converges the exception>
```

An exception may permit a reviewed new subsystem row. It does **not** bypass execution-lifecycle classification, direct model/effect egress controls, or the canonical shared-owner/type guard. If the proposed design needs one of those controls weakened, it is an architecture decision, not a #460 exception.

The exception is deliberately expensive. M1 should normally change the canonical spine or migrate a producer/consumer onto it rather than create another abstraction beside it.

## Enforcement path

The required root test suite executes `tests/test_m1_convergence_freeze.py`. On pull-request and merge-group candidates that test resolves the immutable base SHA from the event payload, fetches that exact commit if a shallow checkout lacks it, and runs `scripts/check-m1-convergence-freeze.py` against `base...HEAD`. Pull-request bodies supply any declared exception plan. Missing base evidence fails rather than silently comparing against a moving branch tip.

Regression tests plant representative second lifecycle, model-egress, Workspace/Event/Checkpoint owner, and shared-type shapes. They also pin immutable base selection for both pull requests and merge groups. This protects the detector itself rather than relying on examples in prose.

## Frozen known competing owners

The current competing owners are already enumerated in `docs/architecture/CONVERGENCE-MATRIX.md` and captured in `quality/m1-convergence-freeze.json`. They are debt to converge or retire, not precedents for creating more.

This policy does not move RSI product convergence into M1. RSI remains M5; shared contracts it will eventually consume are built once in M1.

## Exit

The freeze can be relaxed only after the M1 convergence gates are satisfied and duplicate owners have been retired under #35 after parity proof. Until then, a locally useful new side runtime is still an architectural regression.
