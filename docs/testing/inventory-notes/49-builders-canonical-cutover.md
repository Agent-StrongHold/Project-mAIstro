---
# Issue #49 Builders canonical execution cutover

Issue: #49
Parent: #14

inventory-delta:
  packages/maistro-core/tests: +2
---

## Evidence

The shipped `BuilderPipeline`, `run_builders_dag`, and interactive `maistro builders`
composition construct `CanonicalGraphPipelineExecutor`. Focused tests exercise the
production composition through injected canonical stores and exercise the interactive
TurnRunner adapter through a real canonical Run/NodeRun/Attempt record.

`GraphPipelineExecutor` remains importable only as a compatibility parity oracle;
Builders production callers use the canonical adapter. `PipelineRun` and `DagRun`
retain spec/review/feedback receipt state and canonical identity links, but do not
own generic lifecycle truth.
