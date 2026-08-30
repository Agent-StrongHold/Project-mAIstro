# PR #734 Builders canonical execution inventory note

Issue: #734
Parent: #49

## Claim and collision boundary

This branch owns only the Builders-local migration seam from the private pipeline lifecycle to the existing canonical Graph/Run/NodeRun/Attempt contracts.

Allowed implementation surface:
- `packages/maistro-core/src/maistro/builders/**`
- Builders-focused tests
- this branch-specific evidence note

Explicitly excluded:
- `maistro/container.py`
- `maistro/runs/**`
- `maistro/graph/durable_runs/**`
- migrations and persistence schemas
- quality/reachability ratchets and workflow YAML
- Evolve, Canvas, Design, Turing, Hive/Conductor, Invocation, and provenance packages

If parity cannot be reached through the existing public canonical execution API inside that boundary, this branch records the missing seam rather than modifying shared execution infrastructure.

## Planned evidence

Parity tests will compare representative legacy/private Builders execution with the canonical adapter for stage ordering, ready-wave concurrency, skips, failures, timeout behavior, gate revise/proceed/halt semantics, revision feedback, iteration bounds, and completion ordering.

Canonical evidence tests will inspect the Run store directly and require one Run per pipeline execution, one NodeRun per executed stage, chronological Attempt evidence for physical execution/re-execution, and no Builders-private generic lifecycle authority after projection.

## Inventory delta

To be updated when the focused test set is complete.
