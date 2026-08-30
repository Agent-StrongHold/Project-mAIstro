---
id: ADR-083026-a91e
title: "An unmeasured metric is absent, not zero"
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
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_node_metrics_are_measured.py
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-a91e: An unmeasured metric is absent, not zero

## Context

The Conductor's optimizer ranks DAG variants on four weighted signals. Two of
them — cost at 0.15 and latency at 0.25 — came from `NodeObservation`, whose
`cost_usd`, `tokens_in`, `tokens_out` and `latency_ms` were **required**
fields.

Required fields have to be filled in, and the only production writer had none
of those numbers. `routes/dags.py` supplied `cost_usd=0.0`, zero tokens, the
first node's model behind a hardcoded fallback, and — for latency — the elapsed
time of the whole DAG divided by the cycle count. `_latency_ms` likewise
returned `0` for a NodeRun with no timestamps.

The result is worse than missing data. A zero is a *value*: it ranks. Fed
`cost_usd=0.0` for every node, the optimizer concluded every variant was free
and preferred whichever one it was told the least about. An untimed node
entered the latency percentiles as the fastest in the window. Nothing
distinguished "this cost nothing" from "nobody measured this".

The function that would have produced real observations,
`record_run_completion`, reads canonical `NodeRun` state and materializes the
Run's graph snapshot to recover node types. It had no production caller at all
— every call site was a test — so it was an ingest for a pipeline nothing fed.
`set_store` was the same shape.

## Decision

**A metric nobody measured is `None`, and an aggregate says how many it had.**
The four fields become optional and default to absent. `_aggregate` averages
each over the observations that carry it and reports
`latency_ms_measured` / `tokens_measured` / `cost_measured` beside the value,
so a reader can tell an empty measurement from a zero one. Where nothing was
measured the aggregate reports `None`, not `0.0`.

**A writer supplies only what it observed.** The UI run path records each
node's outcome and identity, which it does know, and nothing else. The
DAG-level timer was removed with the fabrication it fed: it existed only to be
divided.

**An ingest that reads real state gets a real caller, or it does not exist.**
`record_run_completion` is called from `dag_agents.run_registered_dag`, the
canonical execution path. `reset_store` gives `set_store` one too, installing a
fresh buffer per engine start so one process's observations do not leak into
the next one's window.

**A metrics failure is reported, not swallowed.** Both `except Exception: pass`
blocks around metrics writes name the run and DAG whose observations were
dropped. A metrics write must not fail a run that already produced a result;
that is not a reason for the loss to be invisible.

**The module's prose matches its storage.** It is a bounded in-memory buffer
and says so. The three docstrings calling it durable were describing an
intention.

## Related, once it lands

ADR-083026-12f7 (#697) makes a run record declare every field it reports. That
is the same rule one level up: this one is about a value nobody measured, that
one about a field nobody declared, and both produced a number a reader trusted.
It is not listed in `related` because it is still on its own branch, and a
dangling link is worse than a sentence.

## Consequences

### Positive
- The optimizer ranks on measured numbers, and can tell when it has none.
- A run through the canonical path produces observations derived from its own
  NodeRuns rather than from a route's guesses.
- Two dead seams gain callers; `#236`'s wired-but-unread rule is satisfied
  rather than evaded.
- Dropped metrics are findable.

### Negative / Trade-offs
- Every reader of an aggregate must handle `None`. That is the cost of the
  distinction, and the reason the `*_measured` counts sit beside each value.
- The UI run path now records less than it did. What it recorded was invented,
  so this is a reduction in claimed information, not in information.

### Neutral
- Storage is unchanged: still a bounded buffer. Making observations durable
  needs the UI path to mint a canonical Run, which is #53.
