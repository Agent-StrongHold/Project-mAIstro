---
id: ADR-082326-8194
title: "Embedding vectors live on the memory rows, at one declared dimension"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-23
accepted: 2026-08-25
substrate:
  - maistro-engine#ADR-082226-5104
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/migrations/test_memory_embeddings.py
  - packages/maistro-core/tests/memory/learnings/test_durable_hybrid.py
history:
  - status: Proposed
    date: 2026-08-23
  - status: Accepted
    date: 2026-08-25
    reason: "The implementation and PostgreSQL evidence have landed; 1536 dimensions and HNSW are now the accepted schema posture required to close #188."
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082326-8194: Embedding vectors live on the memory rows, at one declared dimension

## Context

`ADR-082226-5104` chose PostgreSQL as the durable system of record and named
**pgvector** as the vector store — no separate vector database. `docker-compose.yml`
runs `pgvector/pgvector:pg17` rather than plain `postgres:17` because of that
choice.

Migration 001 carried it out for exactly one table:

```python
sa.Column("embedding", sa.Text, nullable=True),  # vector(1536) — managed by pgvector
...
op.execute("ALTER TABLE memory_entries ADD COLUMN IF NOT EXISTS embedding vector(1536)")
```

`learnings`, `outcomes` and `episodic_memories` — the tables `maistro.memory`
actually reads and writes — have no such column. The consequence is not merely
"no vector search": it is that similarity cannot compose with scope. Scope
(`org_id`, `team_id`, `agent_id`), provenance, recency and status all live on
the row. With the vector on the same row, a scoped, recent, similarity-ranked
read is one `SELECT`. With the vector anywhere else, it is fetch-by-similarity
then filter-in-Python — slower, and a scope-leak surface, because the filter
stops being the database's job.

### Where 1536 came from

Three dimensionalities are live in the tree today, and no two agree:

| Site | Dimension |
|---|---|
| `alembic/versions/001` — `memory_entries.embedding` | 1536 |
| `memory/learnings/embeddings.py::NoopEmbeddingClient` default | 384 |
| `memory/learnings/embeddings.py::FakeEmbeddingClient` default | 8 |

1536 is the output width of OpenAI's `text-embedding-ada-002` and
`text-embedding-3-small`. **No embedding client is configured anywhere in this
engine** — `EmbeddingClient` has two implementations, both of them test doubles,
and `providers/registry.py` can register embedding-model metadata that nothing
consumes. So 1536 is not this engine's decision; it is a default that arrived
with ported code and has been copied once already.

That matters now because three more tables are about to adopt it. A `vector(N)`
column fixes N in the schema, and changing N later is a migration that rewrites
every stored vector — the cheapest moment to decide is before the column exists
in four places instead of one.

### The tension the protocol creates

`EmbeddingClient.dimension` is a **property of the configured client**, resolved
at runtime. A `vector(N)` column is fixed at migration time. Nothing currently
reconciles the two, so a deployment can configure a 384-dimension client against
a 1536-dimension column and discover it at the first `INSERT`.

## Decision

1. **The vector lives on the memory row.** `learnings`, `outcomes` and
   `episodic_memories` each get an `embedding vector(N)` column, added in the
   shape migration 001 established: extension first, then
   `ALTER TABLE … ADD COLUMN IF NOT EXISTS … vector(N)`.

2. **N = 1536, and it is now a decision rather than an inheritance.** Not
   because 1536 is optimal — for a homelab-scale corpus it is wider than
   necessary — but because `memory_entries` already stores vectors at 1536, and
   a second width in the same database would mean two index strategies, two
   client configurations, and a per-table lookup at every call site. The cost of
   matching an arbitrary existing number is one-off and bounded; the cost of the
   engine holding two widths is permanent. This ADR is the record that it was
   examined and matched deliberately.

3. **The declared dimension is a constant, checked against the client.** A
   single `EMBEDDING_DIMENSIONS` constant is the schema's authority, and a
   configured `EmbeddingClient` whose `dimension` disagrees is refused at wiring
   time with a message naming both numbers — not at the first `INSERT`, and
   never by silently truncating or padding.

4. **The index is HNSW.** The read pattern is interactive recall during a
   request, where latency matters and the corpus is small enough that build time
   does not. IVFFlat is the cheaper build and the worse read: it needs a
   populated table to train its lists, so an index built by a migration on an
   empty table is degenerate, and its recall depends on a `lists` parameter
   nobody will tune. HNSW builds eagerly, needs no training data, and its recall
   is governed by query-time `ef_search` rather than a build-time guess.

5. **Producer and consumer land together, per table.** No table gets a column
   that only writes accumulate in. The migration, the write path that populates
   the vector, and the scope-filtered similarity read ship in one change, or
   none of them does — otherwise this becomes another accepted design with no
   caller, which is what `quality/reachability-baseline.json` exists to count.

   This binds per *table*, not per change. `learnings` has a producer and a
   consumer and gets its column now; `outcomes` and `episodic_memories` do not
   — `PgOutcomeStore` never reads the column and the container wires
   `InMemoryEpisodicStore` even on PostgreSQL — so their columns wait for the
   change that writes them. Giving all three a column because one was ready
   would have been the rule satisfied in aggregate and broken in two places
   out of three.

6. **Filtered recall is configured, not assumed.** HNSW searches approximately
   and applies the scope predicate *after* its candidate scan, so on a large
   multi-org table the candidates can be dominated by other scopes and a scoped
   query returns too few rows — or none — while matching in-scope vectors
   exist. A small corpus never shows it, because the planner picks a sequential
   scan and the filter is exact. `hnsw.iterative_scan = relaxed_order`
   (pgvector 0.8+) is set per transaction on the similarity read: the index
   keeps fetching until the filtered set is full. `relaxed_order` over
   `strict_order` because strict re-sorts every batch to guarantee global
   distance order, at a cost, for a ranking that is already approximate.

## Consequences

### Positive
- Similarity composes with scope, recency and status in one query, with the
  scope filter enforced by the database.
- One width across every table means one index strategy and one client
  configuration.
- A mismatched embedding client fails at startup with both numbers named,
  rather than at the first write.
- The number is written down, so the next person to touch it argues with a
  decision rather than with a copied default.

### Negative / Trade-offs
- 1536 floats per row is roughly 6 KB before compression, wider than a
  homelab corpus needs. Matching `memory_entries` was chosen over right-sizing.
- Changing N later rewrites every stored vector. That is the price of a
  fixed-width column, and the reason this ADR exists.
- HNSW indexes are slower to build and larger on disk than IVFFlat.
- **The width is checked; the model is not.** Two different models can both
  emit 1536 dimensions and occupy entirely different coordinate spaces, so a
  deployment that switches between them passes every check here while its
  stored vectors and its queries stop meaning the same thing — and nothing
  surfaces it, because approximate rankings always return *something*. The
  schema stores no model identity, so there is no predicate that could exclude
  stale vectors and no trigger that could re-embed them.

  Not fixed here, deliberately: a stamp is only useful if something acts on it,
  and the acting part is a re-embedding path this change does not have. Naming
  the gap is the honest half that can ship now. **Until a stamp exists,
  changing embedding model requires clearing the column** — `UPDATE learnings
  SET embedding = NULL` — so the corpus re-embeds on next write rather than
  ranking against a space it no longer shares.

### Neutral
- The `EmbeddingClient` protocol is unchanged; only its reconciliation with the
  schema is new.
- `memory_entries` keeps its existing column; nothing is re-migrated.
