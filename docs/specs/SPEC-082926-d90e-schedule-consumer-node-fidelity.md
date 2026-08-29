---
id: SPEC-082926-d90e
title: Schedule consumer node invocation fidelity
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
  - status: AC Defined
    date: 2026-08-29
substrate:
  - maistro-engine#ADR-082826-b601
implements:
  - maistro-engine#ADR-082826-b601
related:
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-081226-69ee
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_consumption_node_fidelity.py
  - packages/maistro-core/tests/runs/test_human_pause_reasons.py
source:
  - packages/maistro-core/src/maistro/graph/nodes/base.py
  - packages/maistro-core/src/maistro/runs/consumption.py
  - packages/maistro-core/src/maistro/runs/execution.py
  - packages/maistro-core/src/maistro/runs/reconciliation.py
ac-modules:
  AC-1: maistro.runs.consumption
  AC-2: maistro.runs.consumption
  AC-3: maistro.runs.reconciliation
  AC-4: maistro.runs.service
  AC-5: maistro.graph.nodes.base
  AC-6: maistro.runs.reconciliation
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-d90e: Schedule consumer node invocation fidelity

- **Status:** Active
- **Decision:** ADR-082826-b601
- **Closes:** #545

## Context

ADR-082826-b601 gives admitted Runs that no caller drives a canonical consumer.
It says the consumer executes them; it does not say the consumer may execute
them *differently*. Four ways the invocation diverged from the durable graph
executor's, each of which a scheduled template hits and a graph-executed one
does not:

1. `_inputs` merged `{**spec.inputs, **overrides}`. The graph executor composes
   `{**spec.parameters, **spec.inputs}`, and direct-work admission stores a
   node's configuration in `parameters`, so a scheduled template configured the
   canonical way lost required fields — the node then failed validation, or ran
   on defaults.
2. `_resolve` called `get_node(spec.node_type)()`. `build_node_resolver` is
   where `agent.spawn_harness` receives its adapters, `agent.delegate_remote`
   its delegator, guest peers and RunStore, and `rsi.quota_pace_trigger` the
   real usage log. Those kinds pass eligibility, because they *are* registered,
   and then fail or compute against empty state inside a Run that looks
   properly admitted — the shape #147 already had to find once.
3. Any `status != "completed"` raised. A wait or HITL node returning
   `status="paused"` with a successful result has not failed: the Attempt
   recorded a failure, the Run parked WAITING, and `resume_at` plus the pause
   metadata were discarded, so a scheduled `human.*` node could never reach
   PAUSED or surface its prompt.
4. The `NodeContext` was built before execution, when `node_run_id` and
   `attempt_id` are still empty, and the runtime-provided context was ignored.
   Work the node files loses its ancestry, and audit cannot attribute activity
   to the physical Attempt.

## Scope

How the consumer invokes one node. Not what it is allowed to execute
(`consumer_owns` and the source allowlist are unchanged), and not traversal,
which stays owed to the durable Graph path.

## The paused disposition

`AttemptStatus.YIELDED` was already in the canonical model and its transition
table, and nothing produced it. It is the physical outcome for a try that
paused rather than finishing or failing, and this gives it its producer.

`ExecutionYielded` carries the disposition on an exception, the same seam
`RuntimeDeadlineExceeded` uses, so the generic Runtime keeps knowing nothing
about wait or HITL semantics. `AttemptExecutionService.execute` terminalizes
YIELDED and *returns* where the handlers around it re-raise, because a pause is
a disposition rather than an error.

Whether a person is what the pause waits for is recorded **on the Attempt** and
read back from it, not passed alongside it. A process that restarts and
reconciles an already-durable YIELDED row then reaches the same disposition as
the one that wrote it, which is the property the consumer's own docstring
already claims for everything else it does.

WAITING and PAUSED are both parked, and the difference is who is owed the next
action: WAITING means the system owes a retry decision, PAUSED that a person
does. Collapsing them makes a prompt nobody can see indistinguishable from a
provider being down — the reading #230 removed one level up for cancellation.

Which pauses count as "a person" is declared once, in `HUMAN_PAUSE_REASONS`
beside the `pause_until` that carries the reason, and both readers — this
consumer and the durable graph executor — import it. They previously held two
hand-written copies naming two reasons each while nodes raised four, so
`human.review_and_edit` and `human.delegate_to_role` parked WAITING on both
paths. A second literal set is a second thing to forget, and nothing failed
while it was forgotten; a structural test over the node package's AST now
fails when a node pauses for a reason the declared set does not name. System
waits are declared too, as `SYSTEM_PAUSE_REASONS`, so a new pausing node has
to classify itself rather than receiving WAITING by default.

The Run inherits the disposition its last active NodeRun parked with. Parking
the NodeRun PAUSED and the Run WAITING would reintroduce the same collapse one
level up, where the run list and the dashboard actually read it.

**Not in scope here: resuming.** This spec covers what a pause *records*. A
parked schedule Run has no tick that resumes it — `execute_admitted_runs`
polls QUEUED — and requeueing one re-runs its node from the start, which for a
node that dispatched before pausing would repeat the dispatch. That is #641.
Likewise the runtime still counts a successful pause as a failed execution,
because `ExecutionYielded` crosses a broad `except Exception`; that is #642.
Both are real and neither is fixed by this change, so they are named here
rather than left for a reader to discover from the code.

## Acceptance Criteria

```gherkin
Feature: Schedule consumer node invocation fidelity

  @AC-1
  Scenario: A node configured through parameters receives them
    Given a scheduled single-node Run whose node is configured through parameters
    When the consumer tick executes it
    Then the node receives those values
    And the Run completes

  @AC-1
  Scenario: Inputs win over parameters and the schedule wins over both
    Given a node with the same key set in parameters, inputs and the schedule payload
    When the consumer tick executes it
    Then the node sees the schedule's value
    And a key set only in parameters still reaches it

  @AC-2
  Scenario: Nodes are built through the wired resolver
    Given a Container whose resolver carries the canonical RunStore
    When it resolves a delegation node
    Then the node is the dependency-injected one
    And it holds the Container's RunStore

  @AC-3
  Scenario: A paused human node reaches PAUSED with its prompt intact
    Given a scheduled node that succeeds and pauses awaiting a human answer
    When the consumer tick executes it
    Then its NodeRun is PAUSED
    And its Attempt is YIELDED with no error
    And the Attempt records the resume time and the prompt

  @AC-3
  Scenario: A non-human pause parks WAITING rather than PAUSED
    Given a scheduled node that pauses for something other than a person
    When the consumer tick executes it
    Then its NodeRun is WAITING
    And its Attempt is YIELDED

  @AC-5
  Scenario: Every human pause reason is read the same way on both paths
    Given a node that pauses awaiting a human review or a role delegate
    When either the schedule consumer or the durable graph executor reads it
    Then both treat it as a pause a person is owed an action for

  @AC-5
  Scenario: A node cannot pause for an undeclared reason
    Given a node that pauses for a reason the declared set does not name
    When the node package is checked
    Then the check fails rather than defaulting that node to WAITING

  @AC-6
  Scenario: A Run parks in the state its last NodeRun parked in
    Given a scheduled Run whose only NodeRun pauses awaiting a person
    When the consumer tick executes it
    Then the NodeRun is PAUSED
    And the Run is PAUSED rather than WAITING

  @AC-4
  Scenario: The node sees its own NodeRun and Attempt ids
    Given a scheduled node that records the context it was handed
    When the consumer tick executes it
    Then the context carries the NodeRun's id
    And the context carries the Attempt's id
```
