# M8-C1 research note — hybrid vector + graph retrieval vs vector-only Workspace memory

Leaf: #920. Epic: #901. Initiative: #879.

## Hypothesis

Combining semantic vector retrieval with explicit entity/relation traversal improves recall
and evidence quality for long-lived Workspace questions enough to justify added graph
complexity.

## Canonical seams

Durable vector retrieval is `PgLearningStore.find_similar`
(`packages/maistro-core/src/maistro/persistence/pg_learnings.py`): scope-filtered, ordered by
pgvector cosine distance (`<=>`, the `vector_cosine_ops` HNSW index built by migration
`011_memory_embedding_columns.py`, `EMBEDDING_DIMENSIONS = 1536` per ADR-082326-8194),
`max_results`-limited. It is recency-blind — nothing in its score column knows a fact was
superseded. The same is true of the `memory_entries` embedding columns (ADR-083026-4b70).

The graph side already exists as the per-Workspace working-memory projection
(ADR-082226-5104; issues #301/#776): `packages/maistro-core/src/maistro/memory/working/`
ships BM25 lexical recall, embeddings stored at write time, an entity/mention graph with
weighted co-occurrence, bounded `traverse()`, and a composed lexical+vector `recall()`;
`packages/maistro-core/src/maistro/memory/working_graph/` adds the durable-identity projection
(`CanonicalRef`, typed edges, honest health states). What does **not** exist at this head is
the composition the hypothesis is about: no recall ranking seam expands vector candidates
through typed entity/relation edges. The projection's graph structures are explicitly
**disposable** — PostgreSQL + pgvector remain the durable system of record, and a working graph
may be discarded and rebuilt without changing durable truth. The issue's one prohibition
("do not create a second canonical memory store") is therefore already the architecture's own
invariant, and this leaf keeps it: the harness below imports no maistro module at all, so it
cannot become a second authority by accident. ADR-091 keeps Layer 4 (knowledge graph) deferred
pending exactly this kind of evidence.

In-tree latency facts worth citing (measured on the real projection, 100-record Workspaces,
deterministic hashed embedder — `docs/benchmarks/working-memory-baseline.json`, from
`scripts/bench_working_memory.py`): BM25 recall p50 0.204 ms, composed lexical+vector hybrid
p50 1.338 ms (~6.5x), graph traversal p50 0.0065 ms. Traversal itself is essentially free next
to ranking; the cost of a hybrid strategy lives in the extra ranking work and the index
surcharge, both priced below.

## Record

This note does not report a real experiment. The deterministic CI environment holds no
provider embeddings and no real Workspace histories; manufacturing either was out of scope,
and absent evidence is recorded rather than simulated (M8 guardrail 3). No product code, flag,
or authority path changed.

What it adds is the reproducible measurement machinery the benchmark procedure needs, as a
separated research artifact:
`packages/maistro-core/tests/memory/test_m8c1_hybrid_retrieval_research.py` (test suite only;
it imports no maistro module — AST-pinned by its own contract test, M8 guardrails 1-2).
Validated on deterministic hand-checked fixtures (38 checks; six mutation probes — inert
fusion weight, age-blind recency, unbounded budget, dropped provenance chains, no-op
supersession, unanchored expansion — each caught by the suite), it implements:

- a synthetic Workspace-history corpus with ground truth by construction: entities in a
  dependency chain, projects, consumer decisions, temporal fact pairs with supersession, and
  cross-document relations — every record set the issue's experiment description names;
- three strategies: recency-blind cosine top-k (the `find_similar` semantics — the
  "current/vector-only" baseline), cosine x weight x recency (the current working-memory
  policy), and a **bounded, query-anchored hybrid**: vector candidates, one-hop traversal of
  typed dependency edges through entities the query itself names, fusion with a stated beta,
  optional supersession demotion (gamma) — with a hard per-query expansion budget;
- the issue's full measure list: recall/precision, evidence sufficiency (the deterministic
  stand-in for answer/task quality: a generator cannot answer from context lacking the
  evidence), provenance completeness **and** self-containment, work-unit latency accounting
  with nearest-rank p95, storage/index cost in stated per-unit bounds, graph-construction
  error (edge miss/spur rates against ground truth), and sensitivity to stale facts and
  incorrect edges via injected-rate sweeps.

What the fixtures demonstrate (synthetic corpora, **not** evidence about real embeddings or
real Workspaces):

- **The mechanism is real.** Relational evidence whose text shares no token with the query is
  structurally invisible to vector-only retrieval (cosine contributions are exactly 0) and
  reachable by one bounded hop over a dependency edge. On the seeded corpus (relational family,
  k=8): hybrid recall 1.000 / sufficiency 1.000 vs vector-only recall 0.2125 / sufficiency
  0.000. In the hand fixture the multi-hop evidence ranks first overall (fused 1.25 vs the
  best vector hit's 1.0) at the same k where vector-only's sufficiency was 0.
- **The cost is real too.** The same anchoring that finds impact evidence pollutes simple
  factual queries: on the seeded direct family, hybrid recall falls 1.000 to 0.850 and
  sufficiency 1.000 to 0.400 at k=8 — fused dependents' records displace the queried entity's
  own low-similarity records. The relational gain and the direct-family loss are one mechanism;
  a production policy would need query-aware gating, which is exactly the kind of decision
  this benchmark exists to inform.
- **Recency-blind similarity answers with superseded facts.** With content-identical stale and
  current facts, vector-only leads with the stale one (id tiebreak) in 100% of seeded temporal
  queries. The current weight-x-recency policy repairs a single pair; supersession demotion
  (a graph mechanism, gamma = 0.25) repairs it without any recency signal — the relevant
  repair for seams whose score has no recency column at all.
- **Construction error is the failure surface.** At 100% edge miss, hybrid degenerates *exactly*
  to vector-only (the structural downside floor: a wrong graph costs the difference, never the
  baseline). One false "plants depends on auth" edge, pointing at a populated entity, both
  loses the true hop and leads the context with a watering-plants distractor. Rerouting all
  true edges (spur rate 1.0) collapses relational recall from 1.000 to <= 0.45.
- **Fusion can orphan its own justifications.** Provenance chains stay intact (completeness
  1.0), but at k=1 the returned evidence cites a witness outside the returned window
  (self-containment 0.0): fusion promotes admitted records above their admitting candidate. A
  real implementation must reserve a slot for the witness or re-attribute the chain.
- **The surcharge is priced and small at fixture scale.** On the 21-record seeded corpus:
  vectors 43,008 bytes vs graph 424 bytes (entity nodes + membership/dependency/supersession
  edges, stated per-unit bounds); hybrid p95 work 30 vs vector-only 26 units (budget 6).

Executed probe record (head 31d891a561, 2026-10-05):
`uv run pytest packages/maistro-core/tests/memory/test_m8c1_hybrid_retrieval_research.py -q`
-> 38 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module; the
six mutation probes above each produce failures when applied to the harness.

## Benchmark procedure (what a real experiment must do)

1. Export real Workspace histories through the canonical memory seams (durable
   learnings/memories with their scope predicates intact; no scope leaking into the corpus).
2. Hand-audit a relevance sample: per query, the judged-relevant evidence set and the
   known-stale set. Ground truth by hand, not by the retrieval under test.
3. Run the real embedder (the governed `EmbeddingClient` path, ADR-082326-8194 width) for
   candidate generation — the harness's embedder interface takes its outputs unchanged.
4. Compare on the two real seams: `find_similar` (durable, recency-blind) and the working
   projection's ranking path with a gated expansion policy — candidate pool, expansion budget,
   beta, and gamma swept; report the dominance frontier, not a single tuned point.
5. Measure the issue's full list per point: recall/precision, sufficiency, provenance
   completeness and self-containment, wall-clock p50/p95 on the seam (the harness reports
   deterministic work units; only the real seam can answer latency), storage/index cost from
   the live tables, graph-construction error against the hand-audited relation sample, and
   the stale/incorrect-edge degradation curves at injected rates.
6. Report the direct-family cost alongside the relational gain — the fixture result says they
   move together, so a real run that reports only the gain is not done.
7. Update the disposition here. Adoption of any winning policy belongs to the canonical memory
   owners (ADR-034/ADR-091/ADR-082226-5104), as a change to the existing projection/ranking
   seam — never as a second store or a second retrieval authority.

## Trust boundary

Every number the harness produces is advisory evidence: it reads no Goal, writes no Run
authority, touches no durable store, and makes no retrieval decision. The module cannot import
maistro (its own test asserts this by AST), so it cannot drift into becoming a second memory
authority — the issue's prohibition is enforced structurally, not by convention. Ground truth
is frozen at fixture construction; results are frozen dataclasses. A strategy that survives a
real experiment reaches production only through the canonical memory seams and their owners,
where it remains subject to scope predicates as authorization boundaries.

## Disposition

- #920 (hybrid vector + graph retrieval): **WATCH** — the measurement machinery is
  reproducible and its arithmetic is mutation-validated, but no real-Workspace experiment
  exists, so the hypothesis is unevidenced on MAIstro workloads. The fixtures already bound
  the shape of the answer: the gain and the direct-family cost are the same mechanism, and
  construction error is the failure surface.
- Move to **INCUBATE** when a real run on representative histories shows the relational
  evidence gain surviving a query-aware gating policy at a direct-family cost below the
  noise floor, with wall-clock and storage numbers from the live seams and the memory owners
  holding the result.
- Move to **REJECT** if real runs show the direct-family degradation dominating the relational
  gain under honest accounting, or if real extraction error (miss/spur rates measured against
  a hand-audited sample) erases the gain the clean-graph fixtures show.

No adoption is authorized by this note.
