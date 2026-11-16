---
id: ADR-100126-b118
title: "Declared DAG execution budgets are canonical policy: max_cycles is a wave budget, node timeout_s is the Attempt deadline"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-10-01
history:
  - status: Proposed
    date: 2026-10-01
substrate:
  - maistro-engine#ADR-081226-69ee
implements: []
related:
  - maistro-engine#SPEC-177
  - maistro-engine#ADR-082526-237d
supersedes: []
blocks: []
blocked-by: []
contracts: [behavioral]
tests:
  - packages/maistro-core/tests/graph/durable_runs/test_declared_budgets.py
  - packages/hive-conductor/backend/tests/test_canonical_dag_runner.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-100126-b118: Declared DAG execution budgets are canonical policy

## Context

Issue #1184 (M3-B) records that the shipped DAG model advertised controls
execution ignored: `DAGFile.max_cycles` was accepted by the CRUD routes, the
DagBuilder UI, seeds, and evolved genomes, while `graph_from_legacy_dag` never
read it; per-node execution used hard-coded 120-second constants (the sandbox
node script's HTTP timeout, the isolation executor's `timeout_s`, and the
shared LLM HTTP client), and `DAGNode.config` did not participate in timeout
selection. A value is either authoritative input to the canonical policy or it
is not part of the supported contract; fields that only look operational fail
the audit's stop condition.

The canonical executor already owns every ingredient needed to make these
fields real: `AttemptExecutionService` accepts a `timeout_s`, persists it as
`Attempt.deadline_at`, and settles an expired Attempt `TIMED_OUT` via
`ExecutionRuntime`'s deadline enforcement (`RuntimeDeadlineExceeded`); the
durable walk already bounds itself fail-closed by `max_steps` and by each
node's `policies.max_attempts` (`_visit_budget`, ceiling
`MAX_NODE_VISITS = 8`), and deliberately diverges from the legacy `GraphRun`
by refusing to report truncation as success (ADR-081226-69ee parity tests,
ADR-082526-237d).

One reconciliation with prior semantics is required. The durable path
validates legacy DAGs acyclic before execution, so a *re-entry* reading of
`max_cycles` could never bind on the Hive path and the field would remain
dead. The incumbent `GraphConfig.max_cycles` semantics — a budget on
traversal waves — is therefore the contract, enforced fail-closed.

## Decision (proposed)

`maistro.graph.policies` is the single authority that resolves declared
budgets into effective, bounded values:

1. **Cycle budget (waves).** A graph that declares `max_cycles` in its
   metadata gets a frontier-wave budget equal to the declared value clamped
   into `[1, 20]` — the same envelope `GraphConfig.max_cycles` publishes. The
   durable walk refuses to start a frontier once `graph_state.cycle` (the
   persisted wave counter) reaches the budget, and fails the Run
   `CycleBudgetExhausted` with the budget, the completed wave count, and the
   pending frontier named. A DAG whose linear depth exceeds its declared
   budget therefore fails honestly instead of silently; shipped data declares
   budgets covering its own depth (the daily-status seed moves 1 → 5 for its
   five-wave depth). Undeclared budgets change nothing: canonical Graphs
   without the key keep exactly today's floors (`max_steps`, visit budgets).
   The wave budget can never weaken the step floor — both bind in the same
   loop, and the smaller bound wins. Unreadable declarations resolve to the
   tightest cap (1), never the loosest.

2. **Node timeout.** A node that declares `timeout_s` (canonical
   `Node.policies["timeout_s"]`; the Hive adapter lifts
   `DAGNode.config.timeout_s` into it) gets that many seconds as the canonical
   `ExecutionRuntime` deadline for its Attempt: `deadline_at` is persisted
   before launch, expiry settles the Attempt `TIMED_OUT`, and the Run fails
   `AttemptDeadlineExceeded`. Valid values clamp into
   `[1, 600]` seconds; unreadable or non-positive declarations resolve to the
   incumbent default (120s) rather than terminating legitimate work early.
   Undeclared nodes keep today's no-deadline behavior. The legacy node
   adapter's transport constants (sandbox script, isolation executor, shared
   HTTP client) all read the same resolved value — a product-runner timeout
   can agree with the canonical deadline or lose the race to it, but can no
   longer extend work past it.

3. **Provenance over silence.** Clamping never rejects: stored DAGs and
   evolved genomes predate the policy, and rejecting would strand previously
   valid data at read time. Instead both the declared and the effective values
   are recorded — `Graph.metadata` and `Run.provenance` carry
   `max_cycles_declared`/`max_cycles_effective` (and per-node
   `legacy_timeout_s_declared`), the Attempt carries `deadline_at`, and the
   projection result carries `max_cycles_effective` — so any stop is
   explainable from the Run/Attempt record alone. New writes via the DAG
   update route are validated against the same envelope at edit time
   (`UpdateDAGBody.max_cycles: ge=1, le=20`), so out-of-policy budgets are
   refused before they are stored.

## Consequences

- Every declared budget is enforced by the canonical executor; no execution
  path reads a budget the policy did not resolve.
- Stored DAGs with budgets narrower than their depth will fail on their next
  run with the shortfall named; the fix is a value edit, and the failure names
  the exact field.
- A future native Runtime or a second node adapter inherits the same policy
  module; the contract has one home, not per-product constants.

## Alternatives considered

- **Remove `max_cycles`** — honest, but it discards a control the UI, seeds,
  and genomes already model, and the canonical executor was one wire away from
  honoring it.
- **Re-entry budget** — would never bind on the acyclic Hive path; rejected as
  leaving the field dead.
- **Wave budget for all graphs including undeclared** — would silently bound
  every canonical graph that never asked for it; rejected in favor of
  declared-only participation.
