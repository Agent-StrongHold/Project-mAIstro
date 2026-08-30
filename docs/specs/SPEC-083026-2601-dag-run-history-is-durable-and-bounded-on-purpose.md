---
id: SPEC-083026-2601
title: DAG run history is durable, bounded on purpose, and reports what it holds
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
  - maistro-engine#ADR-083026-12f7
implements:
  - maistro-engine#ADR-083026-12f7
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_dag_run_history_durability.py
source:
  - packages/hive-conductor/backend/services/dag_run_store.py
  - packages/hive-conductor/backend/routes/dag_runs.py
  - packages/hive-conductor/backend/routes/dags.py
ac-modules:
  AC-1: '@flat/hive-conductor/services.dag_run_store'
  AC-2: '@flat/hive-conductor/services.dag_run_store'
  AC-3: '@flat/hive-conductor/routes.dag_runs'
  AC-4: '@flat/hive-conductor/services.dag_run_store'
  AC-5: '@flat/hive-conductor/services.dag_run_store'
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-2601: DAG run history is durable, bounded on purpose, and reports what it holds

## Context

`DagRunStore` held run history in a `dict` plus a `deque(maxlen=100)`, behind a
process-global singleton with no setter at all — not even the unused kind the
other Conductor state families carry. The DAG Runs page presents it as history:
"Live DAG Runs" over a "Recent runs" sidebar. It was empty after every restart.

Two defects sat on the same write path. `routes/dags.py` assigned `run.status`
and `run.result` to a dataclass declaring neither, so Python attached them and
`to_summary()` read neither — a completed run reported as still running. And
neither the success nor the failure branch ever called `finish_run`, so
`finished_at` stayed `None` for the life of the process.

ADR-083026-12f7 records the decisions.

## Decision

Run records are persisted through `stores.dag_runs`, part of the same
`_all_json_stores` registry `configure_persistence` already wires. Subscribers
stay in-process, permanently. Reported fields are declared fields, set through
`finish_run`. The retention bound is answerable at `GET /v1/dag-runs/retention`.

Two rules are load-bearing and non-obvious:

**Eviction removes the record too.** A row outliving the working set would come
back on the next load and re-expand history past the bound the deque exists to
hold.

**A reload restores order from `started_at`.** `_order` is a bounded deque
whose eviction must drop the *oldest* run; rebuilt in a store's iteration
order, the next append would evict an arbitrary one — worse than the bound.

## What this deliberately leaves open

`POST /v1/dags/{id}/run` calls `execute_dag`, which mints **no canonical Run**.
The Conductor has two execution paths and only `services/dag_agents.py` reaches
the spine. So `canonical_run_id` is a place for the identity, empty on that
path, and converging it is **#53**.

It is added now so that convergence needs no schema change, and AC-5 states the
gap as a test rather than leaving an empty value to be read as "correlated to
nothing".

## Consequences

### Positive
- History survives a restart and is readable from a second replica.
- A completed run is reported completed, a failed one failed.
- The bound is stated where a client can read it.

### Negative / Trade-offs
- Each event rewrites its run's record. Fine at 100 runs × 200 events; a larger
  bound would want an append-only event table.

### Neutral
- Without persistence the Conductor keeps its previous behaviour, and
  `retention` reports `durable: false` rather than implying otherwise.

## Acceptance Criteria

```gherkin
Feature: DAG run history is durable, bounded on purpose, and reports what it holds

  @AC-1
  Scenario: A run outlives the process that made it
    Given a run with its events and outcome, written to a records store
    When a new store is built on the same records
    Then the run, its status and its events are all readable
    And a second reader of the same records sees the same history
    And a store built without records keeps history process-local instead

  @AC-2
  Scenario: A finished run reports its outcome
    Given a run that has completed, and one that has failed
    When the run list is read
    Then each reports its own status and a finish time
    And the fields it reports are declared on the record, not attached to it

  @AC-3
  Scenario: The retention bound is answerable
    Given a deployment with a durable records store
    When the retention endpoint is asked
    Then it reports durability, the run bound and the per-run event bound
    And the run-id route does not swallow that path

  @AC-4
  Scenario: A subscriber is not part of the record
    Given a run with an open SSE subscriber
    When an event is appended and the record is written
    Then the stored record holds exactly the run's own fields

  @AC-5
  Scenario: A canonical identity is carried, never invented
    Given a run started with a canonical Run id, and one started without
    When their summaries are read
    Then the first carries that id
    And the second reports an empty one rather than reusing its own
```
