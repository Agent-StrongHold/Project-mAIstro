---
# Issue #49 Builders canonical execution cutover

Issue: #49
Parent: #14

inventory-delta:
  packages/maistro-core/tests: +2
---

## Evidence

The shipped `maistro builders` TUI path (`maistro.cli._builders_tui` ->
`builders.interactive`) constructs `CanonicalGraphPipelineExecutor` for its
ReAct turn. `BuilderPipeline` and `run_builders_dag` also construct the same
canonical adapter in their compositions, but today they have no production
caller beyond tests and the `maistro.builders` re-export, so they are not
independent execution authorities. Focused tests exercise both compositions
through injected canonical stores and exercise the interactive TurnRunner
adapter through a real canonical Run/NodeRun/Attempt record.

`GraphPipelineExecutor` is deleted: `maistro.builders.graph_executor` no longer
defines or exports the name (importing it raises `ImportError`), and
`test_canonical_adapter_is_public_and_executor_names_are_not_exported` asserts
the absence so it cannot silently return as a second authority. Builders
production callers use the canonical adapter. `PipelineRun` and `DagRun`
retain spec/review/feedback receipt state and canonical identity links, but do not
own generic lifecycle truth.
