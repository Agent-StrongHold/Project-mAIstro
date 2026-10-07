# Working memory: the per-Workspace Ladybug-shaped hot projection

Implements [ADR-082226-5104](../adr/ADR-082226-5104-storage-architecture-postgres-durable-ladybug-working-memory.md)
§5–§8 and closes the gaps [#301](https://github.com/Agent-StrongHold/Project-mAIstro/issues/301)
names: an empty `DefaultContextAssemblyPolicy.layer4()`, hot episodic retrieval
that re-embeds every candidate per read, and no hydration/eviction lifecycle for
the accepted per-active-Workspace working graph.

## What exists now

`packages/maistro-core/src/maistro/memory/working/`:

| Module | Role |
|---|---|
| `protocol.py` | MAIstro-owned `WorkingMemory` protocol + record types. Every invariant lives here: one graph per Workspace (isolation is structural — there is no operation that addresses two), scope-preserving recall (the same `matches_scope` predicate as the durable stores), explicit `degraded_reason` so nothing can claim graph/vector recall is active when it is not. |
| `projection.py` | `WorkspaceWorkingMemoryProjection` — the first backend: BM25 over a tokenised inverted index, embeddings stored at write time (never recomputed on a read), entity graph with `Entity -> MentionedIn -> Memory` memberships and weighted co-occurrence edges, bounded traversal, idempotent hydrate (content+weight fingerprint), remove-then-insert update path so a content update can never leave the previous content indexed or embedded. |
| `manager.py` | `WorkingMemoryManager` — lazy hydrate from the authoritative `EpisodicStore`, idle-TTL eviction, `rebuild()` (discard + rehydrate; no durable write anywhere on the path), and the failure ledger: backend init failures raise `WorkingMemoryError`, get logged at ERROR, and are recorded in `degraded_reason()`. |
| `extraction.py` | `LexicalEntityExtractor` — the no-LLM path every ordinary operation uses; `GovernedEntityExtractor` — optional complex extraction over a caller-injected async callable that already runs through MAIstro's governed model/effect path. The memory module has no provider client import and must never grow one. |
| `dreaming.py` | `collect_candidates()` — a read-only candidate view (records, hypothesis-tier subset, entities, relations) for a Dreaming Run to consume. The module has no route to any durable store; promotion happens only through the canonical Dreaming Run and the authoritative stores (SPEC-241). |

Wiring: `maistro.container` builds one `WorkingMemoryManager` bound to
`config.workspace_id` ("one instance is one Workspace") and hands it to
`DefaultContextAssemblyPolicy`. Layer 1 goes through the indexed hot path when
the projection is healthy and degrades to the durable retrieval path otherwise;
Layer 4 renders `entity_context()` — real graph-backed context for a populated
Workspace, `""` when there is genuinely nothing being served (no projection,
degraded, or empty graph), never a fabrication.

## Safeguards, and where they live

- **PostgreSQL stays authoritative.** The projection has no write path to any
  durable store. Rebuild is `evict` + `ensure_hydrated`; the conformance tests
  pin that durable state is byte-identical across eviction/rebuild.
- **Cross-Workspace traversal is structurally impossible.** Each Workspace's
  graph is its own object; a traversal reads only its own adjacency map. Tested
  with the hostile case: identical memory ids and entity names in two
  Workspaces.
- **Embedding consistency.** Content updates re-index and re-embed through
  remove-then-insert; a failed re-embed leaves the record honestly
  vector-absent (counted in `stats.embedding_failures`, named in
  `degraded_reason`), never vector-stale. The configured `embedding_model`
  identity is tracked; vectors from a different model are dropped with a
  logged warning rather than silently mixed.
- **No silent failures.** Hydration read failures are logged at ERROR and
  answered with `False` (fallback to the durable path); backend init failures
  raise; governed-extraction failures propagate (and leave the projection
  unmutated — extraction runs before any state change).
- **No replication/CDC/reconciliation.** The projection is disposable by
  construction; there is nothing to reconcile.

## Dependency and licensing review (ADR-039)

ADR-039 assigns maistro-engine the **substrate constraint**: new imports must
satisfy the anti-import bar, because engine dependencies cascade into
Stronghold. Before adding any dependency the review below was performed.

**Candidate:** `ladybugdb` (the LadybugDB embedded graph engine, Kùzu lineage)
and `ladybug-memory` (the Ladybug-Memory reference implementation).

Findings, as of this change:

1. `ladybugdb` **does not resolve from the configured package registry** — a
   hard dependency cannot even lock today. Verified with
   `uv pip install --dry-run ladybugdb` (resolution failure).
2. Maturity/licensing review per ADR-039 §3 therefore cannot conclude favourably
   yet: no maintained release channel to pin, no license file to audit, no
   maintainer-signal evidence to weigh.

**Decision:** implement the MAIstro-owned protocol now, depend on nothing. The
first backend reuses the *patterns* the Ladybug-Memory design validated for
this exact role — BM25 lexical recall, embeddings stored on working-memory
nodes, entity/mention/co-occurrence graph structure — recorded in
[`INSPIRATIONS.md`](../../INSPIRATIONS.md) (pattern references; no code copied).
The `WorkingMemory` protocol is the adoption seam: when `ladybugdb` becomes
resolvable and passes the ADR-039 gate, a `LadybugWorkingMemoryAdapter`
implements the same protocol and the container wires it in the same line.
Nothing above the protocol changes.

This is the outcome issue #301 itself preferred: "It may be preferable to reuse
selected code/patterns while depending only on LadybugDB if that keeps the core
lighter and safer." ADR-082226-5104's §5 decision (LadybugDB as the working
graph engine) stands; this note records that the *dependency* step of that
decision remains open until the package clears ADR-039, and that the working
projection — the part that carries semantics — ships regardless.

## Benchmark

`scripts/bench_working_memory.py` measures the open engineering questions
ADR-082226-5104 names (footprint at scale, hydration strategy cost, workload
latencies) at 1 / 10 / 100 concurrently active Workspace projections.
Deterministic, offline, stdlib-only. First recorded run:
[`docs/benchmarks/working-memory-baseline.json`](../benchmarks/working-memory-baseline.json)
— headline: ~460 KB RSS per 100-record projection at 100 concurrent
Workspaces, hydration ~0.1 ms/record, BM25 p50 ≈ 0.2 ms, hybrid (stored-vector)
recall p50 ≈ 1.3 ms, traversal p50 ≈ 0.006 ms.

## Tests

`packages/maistro-core/tests/memory/working/` — conformance for
hydrate → retrieve/traverse → evict → rehydrate, restart/rebuild, Workspace
isolation, update/re-embed consistency, model-identity drift, failure
observability (hydration read failure, backend init failure, governed extractor
failure), scope preservation, Layer 1/Layer 4 wiring, and the Dreaming
read-only candidate view. See
`docs/testing/inventory-notes/301-working-memory-projection.md`.
