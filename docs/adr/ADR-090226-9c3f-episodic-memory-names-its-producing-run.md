---
id: ADR-090226-9c3f
title: "An episodic memory names the execution that stored it"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-02
accepted: 2026-09-02
history:
  - status: Proposed
    date: 2026-09-02
  - status: Accepted
    date: 2026-09-02
substrate:
  - maistro-engine#ADR-083026-e602
  - maistro-engine#ADR-083026-a322
implements: []
related:
  - maistro-engine#SPEC-090226-e4a1
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_episodic_provenance.py
  - tests/migrations/test_episodic_provenance_migration.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-090226-9c3f: An episodic memory names the execution that stored it

## Context

ADR-083026-e602 gave every durable record of what an execution learned,
measured or made a producer reference — and excluded `episodic_memories` with a
named condition: "provenance on it follows once it has an implementation."
Nothing outside `alembic/` wrote the table then; its only store held a dict.

ADR-083026-a322 met the condition. `PgEpisodicStore` and `SqliteEpisodicStore`
persist the record, the container wires one from the configured backend, and
#622 made ranked episodic recall the read that builds Layer 1 of the prompt.
What an execution *remembered* became a durable, prompt-reaching fact — the
last one in #64's first acceptance bullet with no producing Run behind it.

## Decision

`EpisodicMemory` carries `run_id`, `node_run_id` and `attempt_id`, resolved by
`observed_provenance` under the same rule e602 set: what the caller named wins,
what it left blank comes from the ambient context, and a write with no
execution in scope stores absence. All consequences e602 declared load-bearing
apply unchanged here, because they were decided for the record shape, not the
record kind:

- **Nullable columns; blank means absent.** Migration 031 adds the three as
  nullable `Text`, with one index on `run_id` — "what did this execution
  remember" is the question, and the `produced_by` read narrows from it.
- **Both twins, in the same change.** The SQLite store's `ensure_schema` adds
  the columns in place, so a store file written before this keeps its rows and
  gains the producer — the property that makes a restored SQLite deployment
  preserve the correlated records rather than lose or rewrite them.
- **The in-memory store fills provenance too.** It is the default backend in
  dev and test; a store that skipped this would let every behavioural test
  pass while only the durable ones did the work.

`EpisodicStore.produced_by(run_id, *, org_id="")` lands with it, the same read
`LearningStore` got: given a Run, what did it remember. A blank `run_id`
returns nothing rather than every unattributed memory, and `org_id` is a
predicate in the query — a Run's name cannot widen what a caller can read, the
rule #844 wrote for Outcome reads.

One episodic-specific rule: **the upsert moves the producer with the row.**
Re-storing an existing `memory_id` under a different Run replaces the producer
along with the content; leaving the earlier Run's id would attribute the
surviving memory to an execution that no longer wrote it — the dedup lesson
e602's learnings already learned.

## Consequences

### Positive
- The last memory record kind answers "which execution remembered this", and a
  Run can be asked what it remembered, without changing a single call site —
  `TuringMemoryBridge.store_episode` and every other writer get the ids from
  the ambient context for free.
- A restored or upgraded store keeps the correlation: rows written before the
  columns read back as no-producer, not as a Run whose id is the empty string.

### Negative / Trade-offs
- Three more columns and one index on a table the decay sweep walks; the index
  is not touched by the sweep, which filters on `deleted` alone.
- `produced_by` has no product surface yet, and no keep-alive call was added
  to hide that. Unlike #748's `produced_runs`, it needs no Vulture baseline
  entry: the learning stores already call a `produced_by` of their own from
  src (#709), and Vulture resolves usage by name, so this read is marked used
  and never becomes a finding. The absent consumer is stated here in prose
  rather than recorded — a ledger line for a name Vulture never flags would
  itself fail the baseline's prune check.

### Neutral
- Rows written before this carry NULL and stay valid; nothing backfills them,
  for the reason e602 gave: there is no source for an id that was never
  recorded.
- `InMemoryEpisodicStore` still appends rather than upserts; the durable
  one-row-per-id contract is ADR-083026-a322's and is not changed here.
