---
id: ADR-082526-237d
title: "Derive terminal Run state from a complete logical NodeRun frontier"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
substrate:
  - maistro-engine#ADR-082426-19ed
implements: []
related:
  - maistro-engine#ADR-082426-f170
  - maistro-engine#ADR-082426-a47f
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_run_terminal_derivation.py
  - packages/maistro-core/tests/tasks/test_run_result_projection.py
ac-modules:
  AC-1: maistro.runs.reconciliation
  AC-2: maistro.runs.reconciliation
  AC-3: maistro.runs.aggregation
  AC-4: maistro.runs.reconciliation
  AC-5: maistro.runs.reconciliation
  AC-6: maistro.tasks.execution
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-237d: Derive terminal Run state from a complete logical NodeRun frontier

## Context

ADR-082426-19ed correctly refused one contradiction but deliberately stopped at a guard:
domains still authored the Run terminal status. #237 requires the remaining convergence so
Hive, Canvas, Design, chat, tasks, and Graph do not each own a second parent lifecycle.

The cancellation objection in ADR-082426-19ed remains valid. A requested cancellation, a
deadline, or a traversal/fold failure can end a Run even when every node that actually ran
completed. Those are external Run-level facts and must not be overwritten by a NodeRun fold.

The other missing fact is routing. A generic Run store sees that a Graph node has no NodeRun;
it cannot tell whether that node is still owed or was skipped by a conditional edge.
GraphExecutionState can. Nor does observing every graph node prove completion when the graph
contains a cycle: an already-observed node may still be owed another visit.

There is also a durable-write boundary between accepting a NodeRun outcome and settling its
parent Run. A process can fail after the first write and before the second. Reconciliation is
replayable, so replay must repair that partial commit rather than treating accepted evidence
as proof that the parent fold already happened.

## Decision

When no external Run-level terminal cause has already won and the execution substrate knows
that no logical work is owed, the canonical spine derives the Run outcome from the latest
NodeRun for each executed node. The deterministic precedence is:

1. `FAILED`
2. `TIMED_OUT`
3. `CANCELLED`
4. `COMPLETED`

A non-terminal latest NodeRun (`CREATED`, `QUEUED`, `RUNNING`, `WAITING`, or `PAUSED`) means
there is no terminal Run derivation yet. Retryable failures therefore remain parked rather
than being mistaken for final failure.

The fold does not infer routing. `work_owed` belongs to the substrate that owns traversal.
Direct/fully-materialized Run reconciliation may derive automatically only for an acyclic
Graph when every node in the Run's Graph snapshot has at least one NodeRun. A cyclic Graph
requires actual traversal/frontier truth because node-id coverage cannot prove that a revisit
is not still owed. Durable Graph traversal uses its persisted active/deferred frontier and
then calls the same fold. Conditional nodes that were never selected are therefore neither
failures nor phantom owed work.

An explicitly requested cancellation remains authoritative exactly as ADR-082426-f170
decided. Once such a cause terminalizes the Run, NodeRun aggregation is a no-op; derivation
cannot rewrite terminal history. This scopes around, rather than overturns, ADR-082426-19ed's
cancellation argument.

Accepted NodeRun evidence and parent Run settlement are separate durable writes. Replaying a
persisted completed Attempt whose identical logical outcome is already accepted must retry the
parent fold. Idempotent acceptance therefore means "do not rewrite the NodeRun," not "skip all
remaining reconciliation work."

Product-specific result shape remains a logical projection, not physical evidence. A domain
that needs a different logical payload defers successful automatic reconciliation, persists
the physical Attempt unchanged, and explicitly accepts an `AcceptedNodeOutcome` carrying its
product result. The parent Run still derives from the canonical NodeRun; the product does not
perform a second Run lifecycle transition.

## Acceptance Criteria

- [x] **AC-1**: A one-node Run reaches its terminal Run state when reconciliation accepts its
  terminal NodeRun outcome, with no domain-specific second lifecycle transition.
- [x] **AC-2**: A terminal NodeRun does not terminalize the Run while a sibling is live, and a
  retryable `WAITING` NodeRun does not count as terminal.
- [x] **AC-3**: Mixed terminal NodeRuns use the documented deterministic precedence.
- [x] **AC-4**: Concurrent reconciliation of the final two NodeRuns converges on one valid
  terminal Run instead of producing conflicting parent outcomes.
- [x] **AC-5**: Replaying already-accepted physical evidence repairs a parent Run left running
  between the NodeRun acceptance write and the Run settlement write; generic reconciliation
  does not settle cyclic graphs from node-id coverage alone.
- [x] **AC-6**: A product may keep immutable physical Attempt evidence while accepting a
  narrower logical result, and the derived Run carries that logical product result.

## Consequences

Product adapters keep responsibility for product results/provenance and for genuinely
external Run-level causes. They no longer translate ordinary successful logical node
completion into a separate Run lifecycle decision. When a product result differs from raw
physical evidence, the adapter expresses it once as the accepted NodeRun outcome and the Run
fold remains authoritative. Durable Graph completion consumes the same fold using
GraphExecutionState as the source of owed-work truth.
