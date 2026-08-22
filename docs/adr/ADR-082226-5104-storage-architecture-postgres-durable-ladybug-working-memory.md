---
id: ADR-082226-5104
title: "Storage architecture: PostgreSQL as durable system of record, LadybugDB as per-Workspace working memory"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-08-22
created: 2026-08-22
substrate:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-087
  - maistro-engine#ADR-091
  - maistro-engine#ADR-034
implements: []
related:
  - maistro-engine#ADR-012
  - maistro-engine#ADR-011
  - maistro-engine#ADR-036
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-082126-f69c
  - maistro-engine#SPEC-186
  - maistro-engine#SPEC-244
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082226-5104: Storage architecture — PostgreSQL as durable system of record, LadybugDB as per-Workspace working memory

## Context

The engine's storage story has been undecided in committed form while being treated as
settled in conversation. The result is a repository that contradicts itself:

- `CLAUDE.md` advertises `maistro.persistence` as "PostgreSQL stores"; `README.md` says
  migrations "need Postgres"; `SPEC-070226-fbe3` carries a **checked** acceptance box claiming
  "All persistent state (agents, sessions, memory, audit logs) is in PostgreSQL or Redis".
- No production module imports `persistence.pg_learnings`, `pg_outcomes`, `pg_sessions`,
  `pg_prompts`, `pg_audit`, or `security.pg_strikes`. Only `pg_agents` has a caller.
- `maistro.container` wires the `sqlite_*` stores when `database_url` starts with `sqlite:` and
  otherwise falls through to in-memory. `docker-compose.yml` gives `maistro-engine` five `DB_*`
  variables but no `DATABASE_URL`, and `settings.database_url` defaults to `""` — so the shipped
  stack runs a `pgvector/pgvector:pg17` container, waits on its health check, and connects to
  none of it (#122).
- `SPEC-186` is `Proposed` and unimplemented; `ADR-091` Layer 4 (knowledge graph) is `Deferred`
  and `assemble_layer4()` returns `""`.

Separately, a storage review compared lightweight local graph databases — LadybugDB, ArcadeDB,
Apache AGE, HugeGraph, NebulaGraph, JanusGraph — against two goals at once: a local install that
is small, low-latency and low-burden, and an enterprise deployment with no license cliff.
ArcadeDB was the early favourite because one engine covers graph, document, key/value, vector,
full-text and time-series, which promised to eliminate SQLite, PostgreSQL, a graph DB and a
vector DB together.

That calculation changed when the whole stack was considered rather than the engine alone.
LiteLLM's richer gateway features (keys, spend, budgets, gateway state) use PostgreSQL, and
self-hosted Langfuse requires PostgreSQL plus ClickHouse and Redis/Valkey. **PostgreSQL is
infrastructure the deployment already pays for.** The optimization target therefore moved from
"replace PostgreSQL" to "make PostgreSQL the durable centre, and add another engine only where
it earns a distinct job".

This ADR records that decision so it stops living only in conversation.

## Decision

### 1. PostgreSQL is the durable system of record

One PostgreSQL cluster hosts separate logical databases — `maistro`, `litellm`, `langfuse`. The
separation that matters is **ownership, not infrastructure**: the engine never shares LiteLLM's
or Langfuse's tables or migration namespace, and each application owns its own schema lifecycle
while sharing one HA, backup, monitoring and operational model.

This makes the `pg_*` stores **work to connect, not debt to retire** — reversing the reading in
[#122](https://github.com/Agent-StrongHold/Project-mAIstro/issues/122) before that issue's
`CONNECT`/`RETIRE` question was answered either way.

### 2. pgvector, not a separate vector database

Vectors live in PostgreSQL via pgvector. A memory is an ordinary durable record carrying
`workspace_id`, `persona_id`, `run_id`, content, metadata, provenance, importance **and** its
embedding, so one query combines semantic similarity with workspace and persona filtering, time,
provenance and ordinary relational predicates — no fetching ids from one service to join against
another. LiteLLM stays responsible for routing and model access, including calls to embedding
models; the engine owns the stored vectors and the retrieval semantics.

Qdrant, Weaviate, Milvus and peers are deferred until benchmarks show pgvector has been
outgrown. Note that `README.md` currently states the learnings/outcome stores "have no embedding
column" — closing that is part of implementing this ADR, not a contradiction of it.

### 3. The durable graph is ordinary relational tables plus edge tables

`workspace`, `persona`, `graph`, `node`, `run`, `node_run`, `attempt`, `invocation`, `memory` and
`artifact` stay first-class relational tables. Relationships live in explicit relationship tables
rather than collapsing the domain into one generic vertex table full of JSON, which preserves
foreign keys, constraints, indexes, ordinary SQL, migrations, pgvector and transactions while
still permitting traversal — recursive CTEs where needed, behind a `DurableGraphStore`
abstraction whose first implementation is `PostgresGraphStore`.

This is defensible because the engine's durable relationships are typed, shallow, strongly
scoped and usually workspace-bound — `Workspace → Graph → Run → NodeRun → Attempt → Invocation`,
`Artifact → produced by → NodeRun`, `Memory → learned from → Run`, `Node → uses → Binding`,
`Binding → resolves → Provider`. That is a different workload from a billion-node social graph.

### 4. Apache AGE is optional; PostgreSQL 19 SQL/PGQ is the long-term shape

AGE is **not** required to establish the storage model, and must not become part of the
fundamental storage contract. It earns its place only if Cypher ergonomics materially simplify
the application. PostgreSQL 19's SQL/PGQ is more attractive still, because the property graph is
a **projection over the same relational records** rather than a second authoritative
representation — but today's implementation must work on the production PostgreSQL version and
must not depend on 19.

This narrows `SPEC-186`'s "light up Apache AGE" upgrade trigger from a plan to an option.

### 5. LadybugDB is per-Workspace working memory, never authoritative

Ladybug does not compete with PostgreSQL for durable storage. **PostgreSQL is long-term memory;
Ladybug is fast working memory.** It is an embedded library, not a server — no JVM, no daemon,
no network hop, no Docker dependency — and runs `:memory:` by preference.

Granularity is **one working graph per active Workspace**, not per Run: Runs in the same
Workspace should share hot context. This also gives physical isolation — a traversal in one
Workspace cannot wander into another's working memory because the data is simply absent. It also
defuses Ladybug's single-writer characteristic, which would be alarming for a platform-wide
system of record and is unremarkable for one local runtime's active workspace.

Working graphs are **lazy and evictable**: hydrate on demand, keep hot while active, evict on
idle TTL or memory pressure. 10,000 workspaces with 40 active means roughly 40 live graphs, not
10,000.

### 6. Ladybug is a disposable projection, and may hold what PostgreSQL does not

There is deliberately **no** replication, CDC, distributed consistency, reconciliation, or second
authoritative copy. PostgreSQL is authoritative; Ladybug is hydrated from it, is ephemeral, and
is discarded. **Ladybug failure must never imply durable data loss** — if a projection is
corrupted, throw it away and rebuild it.

Because it is not authoritative, working memory may hold tentative things durable memory should
not: candidate hypotheses, temporary associations, the current plan, retrieved context, inferred
dependencies, the execution frontier. Persisting every such edge immediately would pollute
long-term memory with speculation, so the architecture separates **working hypothesis** from
**durable knowledge**.

### 7. Dreaming consolidates working memory into durable memory, as an ordinary Run

Dreaming is the consolidation process that promotes selected working memory into PostgreSQL. It
deduplicates, clusters, compares, reconciles, validates, scores confidence, summarises, extracts
patterns and preserves provenance. It **does not** dump Ladybug's contents into PostgreSQL — it
decides what deserves promotion. A single transient observation may simply disappear; repeated
evidence across Runs becomes a durable relationship carrying confidence, observation count,
first/last seen and provenance.

Critically, **dreaming is not a private mini-framework**. It is ordinary engine execution:
schedule/trigger → Run → consolidation Graph → NodeRuns → Attempts. That keeps it inside the
convergence spine (ADR-081226-a66b, ADR-082126-f69c) rather than adding an eighth lifecycle, and
means dream executions inherit events, observability, retries, provenance, HITL, artifacts,
security and checkpoints for free.

### 8. The memory hierarchy

| Timescale | Store | Horizon |
|---|---|---|
| Immediate | LLM context window | seconds — current inference |
| Working | Ladybug, per active Workspace | minutes — the active working period |
| Long-term | PostgreSQL + pgvector | durable |

Turing is an **optional** fourth layer *after* consolidation: it consumes consolidated experience
and decides whether it justifies a new template, changed strategy, routing improvement, policy
adjustment, candidate capability or behavioural change. Turing does not replace engine memory and
**dreaming does not require Turing**. This is consistent with ADR-081426-fb9f keeping autonomous
cognition gated.

This answers `ADR-091`'s deferred Layer 4 and `SPEC-244`'s knowledge-graph placeholder.

### 9. SQLite is not a canonical datastore

SQLite began as the obvious lightweight local durable store. Once PostgreSQL is required anyway
and Ladybug covers fast embedded working memory better than SQLite could, a third canonical store
adds little. Small bootstrap or configuration uses of SQLite or a flat file remain acceptable —
`state.py`'s single-writer local state (SPEC-010) is not in question — but SQLite should not be
another canonical datastore without a concrete requirement.

### 10. ArcadeDB is not the chosen architecture

ArcadeDB was not rejected as inadequate; the system-level economics changed. Without
LiteLLM/Langfuse it could plausibly replace SQLite + PostgreSQL + graph + vectors, a real
simplification. With them, PostgreSQL is present regardless, so ArcadeDB becomes a *second*
substantial server database with overlapping capabilities. `PostgreSQL + tiny embedded Ladybug`
has far clearer role separation than `PostgreSQL + ArcadeDB`. Revisit only if the LiteLLM and
Langfuse dependencies change.

### 11. What stays outside the application database

Large artifacts go to object/blob storage. Secrets stay in a dedicated secret store — OS keychain
locally, a cloud secrets manager in hosted environments — never the application database
(SPEC-011). Langfuse keeps its own ClickHouse for high-volume telemetry and Redis/Valkey for
queues and cache.

### Decision summary

| Area | Decision |
|---|---|
| Durable system of record | PostgreSQL |
| Vector storage | pgvector |
| Separate vector DB | No, unless benchmarks require it |
| Durable graph | PostgreSQL tables + explicit relationship tables |
| Apache AGE | Optional, not foundational |
| PostgreSQL 19 SQL/PGQ | Attractive later; no dependency today |
| Working graph | LadybugDB |
| Ladybug lifetime | Lazy, active-Workspace scoped, evictable |
| Ladybug authority | None — disposable projection |
| Ladybug persistence | `:memory:` preferred |
| Workspace isolation | Separate working graph per Workspace |
| Consolidation | Dreaming, executed as an ordinary Run |
| Turing | Optional layer after consolidation |
| SQLite | Not a canonical datastore |
| ArcadeDB | Not the chosen architecture |
| LiteLLM / Langfuse | Separate logical databases, same cluster |
| Large artifacts | Object/blob storage |
| Secrets | Dedicated secret store |

## Consequences

### Positive

- One durable store, one HA/backup/monitoring model, and no second authoritative copy to
  reconcile — the failure mode this architecture most wants to avoid.
- Semantic retrieval composes with relational predicates in a single query, because the embedding
  lives beside `workspace_id`, `persona_id`, `run_id` and provenance rather than in another
  service.
- Each technology has a distinct job: PostgreSQL durability, pgvector semantics, Ladybug fast
  associative traversal, the context window immediacy. No overlapping authorities.
- The conceptual model does not change with deployment size. Laptop, team server and enterprise
  differ only in the number and placement of ephemeral working graphs; the durable data is
  PostgreSQL throughout.
- Dreaming lands inside the canonical Run spine, so it inherits events, retries, provenance and
  security instead of becoming another lifecycle to converge later.
- `ADR-091` Layer 4 and `SPEC-244`'s placeholder finally have an answer.

### Negative / Trade-offs

- PostgreSQL becomes a hard dependency for durable operation. The "no database required" local
  story is gone unless an explicitly ephemeral mode is offered.
- PostgreSQL is not a native adjacency engine. Ladybug will beat it on deep, irregular or highly
  connected traversal; the bet is that the engine's durable relationships are typed, shallow and
  workspace-scoped enough for that not to bind.
- Two storage technologies in the runtime, with a hydration path and an eviction policy to build
  and tune — genuinely more machinery than one store.
- Dream policy is a new correctness surface: promote too eagerly and durable memory fills with
  speculation; too reluctantly and consolidation never happens.
- Adopting LadybugDB adds a dependency whose maturity and licensing must be tracked under
  ADR-039's external-library adoption policy.

### Neutral

- The `pg_*` stores change disposition from candidate-RETIRE to CONNECT in
  `docs/architecture/CONVERGENCE-MATRIX.md`; the reachability debt is unchanged in size, only in
  direction.
- The silent `else` fallback to in-memory stores in `maistro.container` (#122) remains a defect
  under this decision and becomes more urgent, not less: the configured durable backend is now
  the one the code does not wire.
- `docker-compose.yml` already runs `pgvector/pgvector:pg17`, so the image choice is retroactively
  correct; the missing `DATABASE_URL` and dead `DB_*` variables still need fixing.
- `CLAUDE.md`, `README.md` and `SPEC-070226-fbe3`'s checked acceptance box become *aspirational
  but correct in direction* rather than false — they still must not be presented as shipped until
  the wiring exists (#31).

## Open engineering questions

These are empirical rather than architectural, and are deliberately left to measurement:

1. **Ladybug memory footprint at scale** — idle and lightly-populated RAM for 1, 10, 100 and 500
   simultaneous databases; from that, global and per-Workspace budgets.
2. **Hydration strategy** — how much PostgreSQL state to materialise into a working graph, and how
   to select it.
3. **Durable graph representation** — which relationships deserve first-class typed tables versus
   a generic relationship table.
4. **AGE benchmark** — whether Cypher ergonomics justify AGE before PostgreSQL 19 SQL/PGQ is
   production-ready.
5. **Dream policy** — novelty, confidence, recurrence, provenance and contradiction thresholds for
   promotion.
6. **Eviction behaviour** — whether dreaming always precedes eviction, or low-value transient
   graphs may simply vanish.
7. **Langfuse locally** — whether a full self-hosted Langfuse stack belongs on lightweight desktop
   installs at all; it is far heavier than either Ladybug or the engine's own storage.
8. **Workload benchmarks** — graph traversal, vector retrieval, hydration, dream consolidation,
   concurrent Runs, and p95/p99 latency.
