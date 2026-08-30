# #735 Canvas canonical execution evidence

## Scope

This branch converges the `maistro-canvas` generation package onto the existing public canonical execution spine without modifying core stores, durable Graph internals, Design/provenance files, migrations, ratchets, or workflows.

Canvas still owns `GenerationJobRecord`, assets, layer/result paths, selected variants, queue claims, worker leases, retry budget, cancellation receipt, and sanitized Canvas-specific error text. Canonical Run/NodeRun/Attempt records own generic execution history.

## Implemented mapping

1. `CanvasCanonicalExecution` binds a caller-authorized Workspace/Project to the public `RunStore` and `RunExecutionService`. It never derives canonical scope from Canvas `org_id`, canvas ids, layer ids, or placeholder defaults.
2. One accepted generation/refine/reference job admits one canonical Run. The Run id is correlated in the existing durable `GenerationJobRecord.params` JSON, so no schema migration is required.
3. Generate and refine use one canonical NodeRun each. Reference uses hero, side, back, and three-quarter NodeRuns, with each physical provider call recorded as an Attempt.
4. A failed provider call parks the existing NodeRun; a later Canvas retry creates a new Attempt under that same NodeRun. Failed and successful Attempts remain inspectable.
5. A reclaimed Canvas worker lease explicitly fences and reconciles a stranded RUNNING Attempt before redispatch. The final exhausted lease does the same before the Canvas receipt and Run become FAILED.
6. Requested cancellation records canonical physical cancellation with the requested-cancellation disposition before the Canvas receipt becomes CANCELLED.
7. A completed stage is replayed from persisted Attempt evidence instead of reissuing the provider effect.
8. Existing reference behavior is preserved when the hero call returns no URL: the hero Attempt is recorded, downstream reference stages are not fabricated, and Canvas explicitly completes the Run with the existing empty result.
9. `CanvasJobRunner` refuses to claim provider work from a real `CanvasExecutor` that lacks a canonical execution binding. Runner-focused test doubles remain compatible with their narrower claim/retry tests.
10. Existing direct `run_job` remains a compatibility surface for tests/CLI when no canonical binding exists; the background runner path cannot silently use it.

## Focused behavioral evidence

`packages/maistro-canvas/tests/test_canonical_execution.py` currently adds nine focused tests proving:

- scoped Run admission and stage Graph shape;
- successful NodeRun/Attempt evidence;
- failed-then-successful retry under one NodeRun;
- worker-lease reclaim fencing before retry;
- requested cancellation of physical and logical identity;
- four-stage reference execution;
- empty-hero reference short-circuit without fabricated stages;
- completed-stage replay without a duplicate provider call;
- final worker-loss settlement before terminal Canvas failure.

Existing Canvas suites remain the parity evidence for provider error sanitization, layer concurrency exclusion, Warden preconditions, result-path persistence, claim/lease behavior, retry bounds, and receipt semantics.

## Collision boundary

Owned by this branch:

- `packages/maistro-canvas/src/maistro_canvas/canvas/executor.py`;
- `packages/maistro-canvas/src/maistro_canvas/canvas/runner.py`;
- `packages/maistro-canvas/src/maistro_canvas/canvas/canonical_execution.py`;
- focused `packages/maistro-canvas/tests/**` execution evidence;
- this Canvas-specific evidence note.

Explicitly excluded:

- `packages/maistro-design/**` and #711;
- `packages/maistro-core/src/maistro/container.py`;
- `packages/maistro-core/src/maistro/runs/**` and #640;
- `packages/maistro-core/src/maistro/graph/durable_runs/**`;
- repository migrations;
- shared provenance/prompt-digest models;
- quality/reachability ratchets and workflow YAML.

Before claiming, the open PR set was checked for `canvas/executor.py`, `canvas/runner.py`, `test_migration_parity.py`, and #735. No open PR claimed those files or the issue.

## Outer product boundary

The Hive Conductor optional `routes.canvas` mounted in `packages/hive-conductor/backend/main.py` is the older `services.canvas_dag` surface, not `maistro_canvas.canvas.routes`. No repository production composition currently supplies `maistro_canvas.canvas.routes` with an authorized Workspace/Project-bound `CanvasCanonicalExecution`.

This branch therefore does **not** claim that Hive's legacy Canvas entry point has been migrated. It supplies and proves the Canvas-package execution seam that an authorized outer composition can inject, while the cross-package product mounting/cleanup remains parent #52 work. No canonical scope is invented to erase that boundary.
