---
id: SPEC-265
title: "Graph execution exception accounting and node-state invariants"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-177
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - cross-service
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-265: Graph Execution Exception Accounting

## Finding addressed

`GraphRun._execute` runs active node executions with `asyncio.gather(..., return_exceptions=True)` and then infers graph success from `NodeRun.phase`. The returned exception objects are not explicitly inspected.

## Design

1. Capture the `gather` results for each cycle.
2. Assert or convert any unexpected exception result into a failed node state with classified error metadata.
3. Emit an event or diagnostic entry for unexpected node exceptions.
4. Add tests for successful parallel nodes, one node raising unexpectedly, cancellation, and retry exhaustion.
5. Keep `NodeRun.execute` responsible for node-local retries, but make `GraphRun` responsible for orchestration-level accounting.

## Acceptance criteria

- [ ] Gathered exceptions cannot be silently dropped.
- [ ] A node exception produces a failed node in the graph result.
- [ ] A graph event records which role failed and why.
- [ ] Tests cover mixed success/failure active-node cycles.
