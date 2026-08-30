---
id: ADR-083026-12f7
title: "A run record declares every field it reports, and states the bound it keeps"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-082926-3b80
implements: []
related:
  - maistro-engine#ADR-082926-0b72
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_dag_run_history_durability.py
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-12f7: A run record declares what it reports

## Context

The Conductor's DAG Runs page reads `DagRunStore`: a `dict` of runs plus a
`deque(maxlen=100)`, behind a process-global singleton with no setter of any
kind. Three separate things were wrong with it, and they share one cause.

**It was volatile behind a durability affordance.** The page is headed "Live
DAG Runs" over a "Recent runs" sidebar. After a restart it is empty; past 100
runs the oldest are gone. Neither fact was visible anywhere — the bound was a
`maxlen` argument, and the volatility was a docstring reading "v0.5 persists to
postgres".

**A completed run reported nothing.** The run route did:

```python
run.status = "completed"
run.result = result
```

on a dataclass declaring neither field. Python attaches both to the instance,
`to_summary()` reads neither, and the list endpoint therefore showed every run
as still running. This is the failure shape that makes a dataclass worth
having: the assignment succeeded, so nothing was there to fail.

**No branch ever finished the run.** There was no `finish_run` call on success
or on failure, so `finished_at` stayed `None` for the life of the process.

## Decision

**A record's reported fields are declared fields.** Anything `to_summary()` or
`to_detail()` returns is on the dataclass, and a caller changes it by calling a
method that takes it as a parameter — not by assigning an attribute the type
does not have. `finish_run(run_id, *, status, result)` is that method.

**Run history is durable through the store registry the Conductor already
has.** `stores.dag_runs` joins `_all_json_stores`, so run history is persisted
by the same `configure_persistence` call that already backs missions, DAG
definitions, eval verdicts and dashboard layouts. No second persistence path.

**Subscribers are not part of the record, and that is permanent.** A subscriber
is an `asyncio.Queue` held by one open HTTP connection in one process. There is
nothing to serialise and nothing another replica could do with one. The stored
form is asserted by key set, so an attempt to add one fails in a test rather
than at the first `json.dumps` in production.

**A bound that discards data is stated at the API.** `GET
/v1/dag-runs/retention` reports whether history survives a restart and what it
keeps. This is #333's rule — no silent ephemeral downgrade — applied to a
surface that had been presenting a ring buffer as history.

**An identity is carried, never invented.** The record has a
`canonical_run_id`, and the route that runs a DAG from the UI leaves it empty,
because `execute_dag` mints no canonical Run. Filling it with the DAG-run id
would make the record look correlated to a Run that does not exist — the
over-claim the convergence matrix exists to prevent. Converging that path is
#53's.

## Consequences

### Positive
- History outlives the process and is readable from another replica.
- A completed run is reported as completed; a failed one as failed.
- The retention bound is answerable rather than inferable from source.
- The next field added to the record has to be declared to be reported, so this
  class of silent no-op cannot recur here.

### Negative / Trade-offs
- Every mutation now writes through to the registry, so a run with many events
  rewrites its record per event. Acceptable at a 100-run, 200-event bound; a
  larger bound would want an append-only event table instead.
- `canonical_run_id` is a column with no producer on the main path until #53.
  A field waiting for a caller is the shape #236 gates against — kept because
  the alternative is a schema change inside that convergence, and because a
  test states the gap rather than leaving the empty value to be read as
  "correlated to nothing".

### Neutral
- A Conductor started without persistence keeps its previous behaviour. What
  changes is that `retention` says so.
