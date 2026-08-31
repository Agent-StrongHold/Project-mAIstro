---
id: ADR-083026-e602
title: "A record names the execution that produced it, filled from the ambient context"
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
  - maistro-engine#ADR-083026-1cb1
  - maistro-engine#ADR-019
implements: []
related:
  - maistro-engine#SPEC-083026-b2b5
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_record_provenance.py
  - packages/maistro-design/tests/test_output_provenance.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-e602: A record names the execution that produced it, filled from the ambient context

## Context

Three tables record what the system learned, measured or made, and until this
decision not one could answer "which execution produced this".

`learnings` had no producer field at all; its closest thing was `source_query`,
the text of the request. A learning is a correction the system applies to future
work — it changes behaviour — so a bad one could not be traced back to the run
that taught it, which is the first question anyone asks.

`outcomes` was the near miss. Migration 010 gave it `dag_id`, `dag_run_id` and
`node_id`: the Conductor's product-specific DAG identity, which ADR-019 puts on
the product side of the split. The canonical Run/NodeRun/Attempt those DAG runs
execute as (#143, #223, #697) went unnamed — and outcomes are what the router's
scoring and the optimizer's fitness read, so this is the evidence path behind
automated decisions.

`design_outputs`, the engine's one persisted artifact table, shipped an artifact
to a user with no record of what made it.

The ids were never unavailable. They were held by a caller several frames above
the write, and passing them meant threading four arguments through every
intervening signature in three subsystems — which is why it kept not happening.
ADR-083026-1cb1 removed that obstacle by making the execution context ambient.

## Decision

Every durable record of what an execution learned, measured or made carries
`run_id`, `node_run_id` and `attempt_id`, resolved by `observed_provenance` —
**what the caller named wins; what it left blank comes from the ambient
context.** The same rule `EventEnvelope.correlated` follows, for the same reason:
a caller recording a fact *about* another execution knows something the context
does not, and a caller that simply did not think about it gets the truth free.

Four consequences of that rule are load-bearing:

**Nullable columns, and blank means absent.** A record written with no execution
in scope stores SQL NULL. `''` would read as "produced by a Run whose id is
empty" — a claim — where absence reads as "no execution was in scope", which is
what happened. This is the same over-claim #698 removed from node metrics.

**The DAG identity stays.** `outcomes.dag_run_id` and `node_id` name a real
hive-conductor object the Conductor UI reads. The canonical ids sit *beside*
them, not instead of them; replacing a product identity with a canonical one is
a different decision and would break a working surface.

**Both twins, in the same change.** A SQLite twin that silently drops what
PostgreSQL persists passes every test written against the twin alone; #696
found three such drops in one store. The twins gain the columns with an in-place
`ALTER TABLE` so a file that already holds learnings keeps them.

**The in-memory store fills provenance too.** It is the default backend in dev
and test, so a store that skipped this would let every behavioural test pass
while only the durable ones did the work — which is how a claim ends up resting
on the one implementation that cannot check it.

Recording without a read is bookkeeping, so `LearningStore.produced_by(run_id)`
lands with it: given a Run, what did it teach. All four implementations answer
it, and a blank `run_id` returns nothing rather than every unattributed row —
"which learnings did no execution produce" is a legitimate question and a
different one, and answering it from the same call means a caller with an
unresolved id silently gets the wrong set.

`episodic_memories` is deliberately excluded. Nothing outside `alembic/`
references that table and its only store implementation holds a dict, so
columns there would be a durability claim with nothing behind it. Filed as
#710; provenance on it follows once it has an implementation.

## Consequences

### Positive
- A learning, an outcome or an artifact can be traced to the execution that
  produced it, and a Run can be asked what it taught.
- Producers get correct provenance without changing a single call site.
- The evidence behind the router's scoring and the optimizer's fitness names
  canonical execution identity rather than one product's DAG identity.

### Negative / Trade-offs
- Three more columns and one index per table. The index is on `run_id` only:
  "what did this execution produce" is the question, and indexing the NodeRun
  and Attempt too would cost three writes per row to serve a narrowing that a
  `run_id` lookup already makes cheap.
- The in-memory store mutates the caller's `Learning` to record the producer.
  It already keeps and returns that same instance, so provenance held anywhere
  else would not survive the read.
- Provenance is only as good as the binding above it. A write path reached with
  no execution bound records nothing — visibly nothing, which is the point, but
  it does mean the value of this decision grows as more seams bind.

### Neutral
- Rows written before this carry NULL and stay valid. Nothing backfills them:
  there is no source for an id that was never recorded.
- The SQLite outcomes twin still lacks eight columns PostgreSQL carries
  (`org_id`, `project_id`, `dag_id`, `dag_run_id`, `node_id`, `thumb`,
  `thumb_comment`, `eval_judge_score`) and still writes `tool_calls` with
  `str()` rather than JSON. That divergence is real, predates this decision and
  is not this one's to close.
