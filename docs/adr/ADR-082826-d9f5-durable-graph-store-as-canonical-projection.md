---
id: ADR-082826-d9f5
title: "The durable Graph store becomes a projection over the canonical Run store"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-28
accepted: 2026-08-28
history:
  - status: Proposed
    date: 2026-08-28
  - status: Accepted
    date: 2026-08-28
substrate: []
implements: []
related:
  - maistro-engine#ADR-081226-69ee
  - maistro-engine#ADR-082126-f69c
  - maistro-engine#ADR-082826-b601
  - maistro-engine#ADR-082526-237d
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/graph/durable_runs/test_canonical_identity.py
  - packages/maistro-core/tests/graph/durable_runs/test_canonical_execution_store.py
  - packages/maistro-core/tests/graph/durable_runs/test_canonical_durable_store.py
  - packages/hive-conductor/backend/tests/test_dag_agents.py
  - packages/maistro-core/tests/graph/durable_runs/test_legacy_archive.py
ac-modules:
  AC-1: maistro.graph.durable_runs.executor
  AC-2: maistro.graph.durable_runs.execution_store
  AC-3: maistro.graph.durable_runs.spine
  AC-4: maistro.graph.durable_runs.canonical_store
  AC-5: maistro.graph.durable_runs.continuation
  AC-6: maistro.graph.durable_runs.legacy_archive
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082826-d9f5: The durable Graph store becomes a projection over the canonical Run store

## Context

#44 asks for durable Graph execution to be converged onto Run + GraphExecutionState. Read
quickly, that sounds like a model problem. It is not: **the models already converged.**
`DurableRunRecord` holds a real `Run`, real `NodeRun`s and real `Attempt`s
(`graph/durable_runs/types.py`) — the work #42 and #43 finished.

What did not converge is the **store**. `DurableRunStore` persists that aggregate as one
document (`InMemoryDurableRunStore`, `SqliteDurableRunStore`), while `RunStore` keeps the same
three entities in three tables with their own lifecycle, fencing, retention and recovery. Two
stores hold the same kind of record and neither can see the other's.

Every symptom below is that one split, met from a different direction:

- `GET /v1/runs/{run_id}/node-runs` cannot see graph NodeRuns, because they are inside a
  document the canonical store does not hold (#251 records this).
- `services/dag_agents.py` executes every registered Hive DAG against a **module-level
  `InMemoryDurableRunStore`**. Those executions are process-local: invisible to the spine, gone
  on restart. This also falsifies ADR-082126-f69c's claim that schedule fires produce canonical
  Runs "via `dag_agents.py`".
- #231 cannot migrate the live scheduler onto `ScheduleRunAdmitter`. Admitting canonically and
  executing through `run_registered_dag` gives one occurrence two records; admitting without
  executing gives a Run that sits `QUEUED`, which is the defect #251 exists to remove.
- Recovery (ADR-082826-08f0) and retention (ADR-082226-f436) operate on the canonical store, so
  a crashed or expired graph execution is reached by neither.

The pattern to avoid is the one ADR-081226-69ee already named for `GraphRun`: a second execution
universe that looks supported because a test uses it.

## Decision

**`DurableRunStore` becomes a projection over `RunStore`, not a peer of it.**

1. The canonical `RunStore` is the sole system of record for `Run`, `NodeRun` and `Attempt`,
   including those produced by Graph traversal. Graph execution writes them through it.
2. `GraphExecutionState` and the traversal records that belong only to Graphs — frontier, visits,
   blackboard, routing, `TraversalCheckpoint`, `TraversalCommit` — remain Graph-specific state,
   stored beside the canonical entities and keyed by `run_id`. Converging the execution identity
   does not mean flattening traversal state into it; #44 asks for exactly this separation.
3. `DurableRunStore` is kept as an **interface**, reimplemented over the canonical store, so
   existing callers (`run_durable_graph`, HITL resume, the Hive surfaces) keep their shape while
   the records move. The document-shaped implementations become migration projections or are
   removed.
4. `dag_agents.py`'s module-level `InMemoryDurableRunStore` is **retired**, not converted. A
   process-local store for durable work is the defect, not an implementation of it.

Deliberately not decided here: the physical schema for traversal state, and whether
`SqliteDurableRunStore` keeps a homelab twin. Both are implementation questions for the spec this
ADR will carry, and neither changes the boundary above.

## How: the executor obtains identity, rather than an adapter replaying it

Recorded here because the first plausible route is a trap, and the evidence
against it is cheap and worth keeping.

The tempting route is an adapter: implement `DurableRunStore` over the canonical
store and have `update()` diff the incoming record against what is stored,
replaying the difference as transitions. It is reversible and its test is the
existing conformance suite. It does not work, for a reason that is structural
rather than fiddly:

**Identity is minted on the models, and the canonical creates do not accept it.**
`Run`, `NodeRun` and `Attempt` each carry `Field(default_factory=_id)`, and
`create_run`, `create_node_run` and `create_attempt` take no id parameter — each
constructs its entity and lets it mint. The executor, meanwhile, constructs those
models itself and hands finished documents to `create()`/`update()`, so every id
in a `DurableRunRecord` exists before the canonical store has seen it.

An adapter would therefore need all three creates to accept externally-minted
ids, purely so a document-shaped caller can keep identities it assigned first.
That inverts identity ownership in the store that this ADR is making the system
of record — the canonical store would be told what its identities are by its
caller. A second mismatch sits behind it: the executor is a whole-document
writer (`store.update(_replace_record(record, version=record.version + 1, ...))`)
against a store that exposes only lifecycle-validated transitions.

So the direction is the other one: **traversal obtains identity from the
canonical store as it goes**, and the `DurableRunRecord` becomes something
assembled from what the store returned plus the graph-specific state, rather
than something the executor mints and then persists. Concretely that means the
executor's construction sites — `traversal._new_run` and the NodeRun/Attempt
creations — become store calls, which is more surgical than "rewrite the
executor" and is the same change either way.

`execution_store.py` is the asset here: it is already a `RunStore`-compatible
view over durable records, so `AttemptExecutionService` speaks `RunStore`
against graph work today. The Attempt half of the seam exists; what moves is
where the identities come from.

## Acceptance Criteria

- **AC-1**: A Run executed by either durable Graph entrypoint is created by
  `RunStore`, so it resolves through `get_run`, appears in `list_by_status`,
  and carries the scope and provenance of a canonical row. A caller with no
  `RunStore` wired still runs, on the pre-convergence path.
- **AC-2**: Every NodeRun and Attempt of such a Run is created by `RunStore`
  too, with the guards that used to be duplicated in
  `DurableRunExecutionStore` enforced once. A record's own precondition — that
  this Run is finished with a node — still refuses an Attempt the aggregate
  cannot carry.
- **AC-3**: Lifecycle applied in the aggregate is written back to the store
  that owns the entity, by walking the shortest legal path through
  `RUN_TRANSITIONS` rather than jumping or overwriting, so a canonical row
  never reads differently from the record for the same entity. A terminal
  status raises rather than silently doing nothing.
- **AC-4**: `CanonicalDurableRunStore` satisfies `DurableRunStore` by writing
  the record's two halves to the two stores that own them and assembling reads
  from both. It refuses a record whose Run the spine has never seen rather than
  minting a second identity for it.
- **AC-5**: Graph continuation state is persisted beside the canonical Run in
  the same database the spine chose — in memory, SQLite, or PostgreSQL — and a
  paused HITL frontier is answerable and resumable across a process restart.
- **AC-6**: A durable graph run persisted *before* this convergence still
  reproduces afterwards — its Run, NodeRuns, Attempts and traversal history all
  read back through the canonical models — and is refused resumption by name
  rather than re-admitted under a new identity. Proven against a database
  captured from the pre-convergence store and committed as a fixture, not one
  generated by the current models.

## Consequences

### Positive

- One store answers "what happened in this execution", so the run-inspection API, recovery,
  retention and the schedule cursor all see graph work without each growing a special case.
- #231 becomes mechanical: admit through `ScheduleRunAdmitter`, execute through the canonical
  traversal, one Run per occurrence.
- ADR-082126-f69c's falsified claim becomes true rather than being amended into vagueness.
- The remaining `GraphRun`-era universal lifecycle owner disappears, which is #44's fourth
  acceptance criterion and the last of ADR-081226-69ee's retirement.

### Negative / Trade-offs

- This is a storage migration, not a refactor: historical `DurableRunRecord`s must remain
  readable, which #44's fifth criterion requires and which is the bulk of the work.
- The document store's single-write optimistic-concurrency model becomes several writes across
  canonical tables. Traversal already checkpoints, so the seam exists — but the concurrency
  argument has to be made explicitly rather than inherited.
- Multi-node execution stays unavailable to the consumer tick until this lands, so #231 and the
  multi-node half of #251 stay open longer than either would in isolation.

### Neutral

- No change to `Run`, `NodeRun` or `Attempt` themselves; they are already canonical.
- `GraphExecutionState` keeps its shape and its owner.
