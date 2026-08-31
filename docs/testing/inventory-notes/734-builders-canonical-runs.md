# PR #734 Builders canonical execution inventory note

Issue: #734
Parent: #49

inventory-delta:
  packages/maistro-core/tests/: +7

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

## Evidence

Seven focused behavioral tests compare representative legacy/private Builders execution with the canonical adapter for ready-wave ordering/concurrency, skips and unsupported stages, failure and timeout behavior, gate revision feedback, iteration bounds, and canonical completion projection.

Canonical evidence directly inspects the Run store and requires one canonical Run per pipeline execution, canonical NodeRun/Attempt evidence for physical stage execution and re-execution, and Builders domain state to remain a projection rather than a second generic lifecycle authority.
