---
id: SPEC-083026-2642
title: Node metrics are measured or absent, and the ingest that reads them has a caller
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
  - status: AC Defined
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-083026-a91e
implements:
  - maistro-engine#ADR-083026-a91e
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_node_metrics_are_measured.py
source:
  - packages/hive-conductor/backend/services/node_metrics_store.py
  - packages/hive-conductor/backend/services/dag_agents.py
  - packages/hive-conductor/backend/services/optimizer.py
  - packages/hive-conductor/backend/services/topology_compare.py
ac-modules:
  AC-1: '@flat/hive-conductor/services.node_metrics_store'
  AC-2: '@flat/hive-conductor/services.node_metrics_store'
  AC-3: '@flat/hive-conductor/services.dag_agents'
  AC-4: '@flat/hive-conductor/services.optimizer'
  AC-5: '@flat/hive-conductor/services.node_metrics_store'
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-2642: Node metrics are measured or absent

## Context

`NodeObservation` required `latency_ms`, `tokens_in`, `tokens_out` and
`cost_usd`. Its only production writer measured none of them, so
`routes/dags.py` supplied zeroes, a hardcoded model name, and the whole-DAG
elapsed time divided by the cycle count — inside a bare `except Exception:
pass`.

The optimizer weights cost at 0.15 and latency at 0.25. A zero is a value that
ranks, so it scored every variant as free and every node as equally fast.

`record_run_completion`, which reads canonical NodeRuns and materializes the
Run's graph snapshot for node types, had no production caller. Neither did
`set_store`. Two production readers — `optimizer._collect_node_metrics` and
`topology_compare` — reached into `store._filter` and imported the
module-private `_aggregate`.

ADR-083026-a91e records the decisions.

## Decision

The four fields are optional and default to absent. Aggregates average each
over the observations that carry it, and report how many that was. Writers
supply only what they observed. The ingest and the setter get production
callers. Readers use the store's public surface.

## What this deliberately leaves open

The buffer stays in memory and bounded, and the module now says so instead of
calling itself durable. Making the observations durable needs the UI run path
to mint a canonical Run, which `execute_dag` does not — that is **#53**, the
same blocker SPEC-083026-2601 records for run history.

## Consequences

### Positive
- The optimizer ranks measured numbers and can tell when it has none.
- A canonical run's observations come from its own NodeRuns.
- Dropped metrics are findable rather than silent.

### Negative / Trade-offs
- Readers of an aggregate must handle `None`; the `*_measured` counts beside
  each value are what make that tractable.
- The UI path records less. What it recorded was invented.

### Neutral
- Storage is unchanged.

## Acceptance Criteria

```gherkin
Feature: Node metrics are measured or absent

  @AC-1
  Scenario: An unmeasured cost is not a zero cost
    Given observations that carry no cost, and one that carries a real cost
    When each window is aggregated
    Then the unmeasured window reports no cost measured and no total
    And the measured one reports its total

  @AC-2
  Scenario: An average divides by what was measured
    Given one node timed at 100ms beside one that was not timed
    When the window is aggregated
    Then the mean is 100ms, not 50ms
    And an untimed node does not enter the latency percentiles

  @AC-3
  Scenario: The canonical run path records its own NodeRuns
    Given a finished durable run record
    When the canonical execution path completes
    Then the metrics ingest is called with that record
    And the fields the durable slice does not carry are left absent
    And a NodeRun with no timestamps has no latency rather than zero

  @AC-4
  Scenario: Readers use the store's public surface
    Given the optimizer and the topology comparison
    When their source is inspected
    Then neither reaches a private helper of the metrics store
    And the public surface answers the same question

  @AC-5
  Scenario: Each engine start gets its own buffer
    Given a store holding a previous process's observations
    When the metrics store is reset
    Then the process store is a fresh empty buffer
    And the engine performs that reset at start
```
