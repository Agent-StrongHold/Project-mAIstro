# M1 Convergence Freeze

**Owner:** #460  
**Policy data:** `quality/m1-convergence-freeze.json`

M1 is a convergence milestone. Until Gates A-E are complete, adding another universal owner is a regression even when the new module is locally well designed.

## Default rule

Do not add a new universal work lifecycle, Run identity, traversal authority, model/tool effect path, or execution-authoritative event bus during M1.

New product behavior must enter the Accepted architecture:

- execution truth: `Run → NodeRun → Attempt → ExecutionRuntime`
- traversal truth: `GraphExecutionState` attached to Run
- governed effects: `Capability → Provider → Binding → Invocation`
- shared cross-product semantics: the versioned ontology owned by #458

Domain-specific state remains allowed. A renderer may own render state; a collaboration feature may own edit-session state; a scheduler may own trigger/cursor state. What it may not do is turn that domain state into another general-purpose execution authority.

## PR rule

A PR that introduces a new package or service whose responsibility could own execution lifecycle, traversal, or governed effects must either:

1. map it explicitly to an existing canonical owner and remain a projection/adapter/provider, or
2. carry the `m1-convergence-exception` label and document all of:
   - why the canonical owner cannot represent the requirement,
   - the exact semantic boundary of the new authority,
   - its convergence or retirement path,
   - why it does not recreate a product island.

The exception is deliberately expensive. M1 should normally change the canonical spine or migrate a producer/consumer onto it rather than create another abstraction beside it.

## Frozen known competing owners

The current competing owners are already enumerated in `docs/architecture/CONVERGENCE-MATRIX.md` and captured in `quality/m1-convergence-freeze.json`. They are debt to converge or retire, not precedents for creating more.

This policy does not move RSI product convergence into M1. RSI remains M5; shared contracts it will eventually consume are built once in M1.

## Exit

The freeze can be relaxed only after the M1 convergence gates are satisfied and duplicate owners have been retired under #35 after parity proof. Until then, a locally useful new side runtime is still an architectural regression.
