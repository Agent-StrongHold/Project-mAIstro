# #735 Canvas canonical execution claim

## Claim

Canvas generation currently owns a private execution lifecycle in `GenerationJobRecord.status`. `CanvasExecutor` performs physical provider calls while `CanvasJobRunner` owns claim/retry/cancel transitions, but neither writes canonical Run/NodeRun/Attempt evidence.

This branch will converge only the Canvas execution package onto the existing public canonical `RunStore` contract. It will not modify core stores, durable Graph internals, Design/provenance files, migrations, ratchets, or workflows.

## Implementation plan

1. Introduce a Canvas-local canonical execution adapter around the public `RunStore` API. The adapter receives an already-authorized canonical scope/admission context from its constructor or caller; Canvas does not derive a Workspace/Project identity from `org_id`, asset ids, or standalone placeholders.
2. Admit exactly one Run per user-requested generation operation when the caller supplies scope, or consume an already-admitted Run when one is supplied.
3. Map each physical Canvas generation/refine/reference stage to one NodeRun beneath that Run.
4. Wrap every provider execution, including retries, in a distinct canonical Attempt. Failed Attempts remain inspectable; a later retry creates a new Attempt under the same NodeRun.
5. Keep `GenerationJobRecord`, assets, layer/result paths, selected variants, cancellation receipt and Canvas-specific error semantics as Canvas domain state. Its status becomes a projection/receipt, not generic execution authority.
6. Preserve existing runner claim/lease/requeue behavior while correlating each claimed execution to canonical evidence. Do not move Canvas queue leasing into core.
7. Extend migration-parity tests before demoting any lifecycle behavior: completion, sanitized provider failure, cancellation, retry/lease, layer concurrency exclusion, Warden preconditions and result persistence.
8. Add direct evidence that a failure followed by retry leaves failed and successful Attempts under the same NodeRun.
9. Run the complete Canvas suite and required repository CI. If the public `RunStore`/Graph contracts cannot support this without a forbidden core edit, stop and record the missing seam.

## Collision boundary

Owned by this branch:

- `packages/maistro-canvas/src/maistro_canvas/canvas/executor.py`;
- `packages/maistro-canvas/src/maistro_canvas/canvas/runner.py`;
- a new Canvas-local execution adapter under `packages/maistro-canvas/src/maistro_canvas/canvas/`;
- Canvas domain types only if narrow correlation fields are required;
- `packages/maistro-canvas/tests/**` focused on execution/parity;
- this Canvas-specific evidence note and any branch-local suite inventory note required by gates.

Explicitly excluded:

- `packages/maistro-design/**` and #711;
- `packages/maistro-core/src/maistro/container.py`;
- `packages/maistro-core/src/maistro/runs/**` and #640;
- `packages/maistro-core/src/maistro/graph/durable_runs/**`;
- repository migrations;
- shared provenance/prompt-digest models;
- quality/reachability ratchets and workflow YAML.

Before claiming, the open PR set was checked for `canvas/executor.py`, `canvas/runner.py`, `test_migration_parity.py`, and #735. No open PR claims those files or the issue.
