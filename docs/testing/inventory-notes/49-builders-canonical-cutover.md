---
# Issue #49 Builders canonical execution cutover

Issue: #49
Parent: #14

## Suite inventory

No `inventory-delta` block: this branch moves no suite count. The two Builders
suite files an earlier draft of this note claimed
(`packages/maistro-core/tests: +2`) are already part of the develop baseline
this branch rebuilt onto, so the stale `+2` was removed -- it double-counted
and drifted `packages/maistro-core/tests` by net -2. The parity-suite changes
rewrite existing scenario tests without adding or removing any.
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

### Strict #459/#1036 inspection scenario (repair round)

`tests/cross_product_parity` scenario 1
(`builders-producer-to-conductor`) is now a real execution, replacing the
abstaining scaffold: the producer half runs the shipped Builders interactive
composition (`CanonicalInteractiveTurnExecutor` ->
`CanonicalGraphPipelineExecutor`, the executor the CLI process opens through
`BuildersExecutionSpine`) over the supported durable SQLite spine inside a real
canonical Workspace, and the observer half inspects and controls the same
canonical Run id through Conductor's landed seam (`services.dag_run_inspection`
list/detail plus the #1169 `POST /v1/dag-runs/{id}/cancel` route wired to the
same stores). The scenario requires: no `DagRunStore` projection row, list and
detail answered by canonical id alone, readable NodeRun/Attempt evidence, a
foreign-Workspace observer refused identically to a missing id, and a
mid-flight turn fenced CANCELLED through Conductor's cancel so the Builders
turn can never publish success over canonical truth.
`REAL_BUILDERS_CONDUCTOR_SCENARIO`'s marker therefore reads as available, and
`test_builders_required_scenario_emits_strict_closeout_evidence` asserts PASSED
closeout evidence in both modes. Scenarios 2 (schedule), 3 (Evolve), and 6
(golden observation) remain named blockers owned by #231, #51, and #463; the
strict closeout stays red for them by design.
