# M8-C2 research note — learned reranking and query rewriting for Workspace retrieval

Leaf: #921. Epic: #901 (M8-C). Initiative: #879.

## Hypothesis

A learned or LLM-assisted reranker/query rewriter can improve relevant-evidence selection
over raw embedding similarity without unacceptable latency or semantic drift.

## Canonical seams

The retrieval seam this leaf evaluates against is episodic memory ranking (SPEC-243 /
ADR-080 part D): `packages/maistro-core/src/maistro/memory/episodic/ranking.py` owns the
formula — `(keyword_overlap + cosine) * memory.weight`, with `keyword_overlap` (raw
word-split tokens, no stopword removal) as the lexical term and `no_vector` as the term
when no embedding client is configured — and `packages/maistro-core/src/maistro/memory/episodic/retrieval.py`
(`ScoredEpisodicRetrieval`) owns the two-stage shape: the store recalls a scoped pool of
`limit * 10` candidates, the formula reranks it. SPEC-243 lists "query expansion / reranking
beyond the single hybrid score formula ADR-080 specifies" as an explicit **Non-goal**, so
any reranker or rewriter this leaf could justify ships, if ever, through the retrieval
owner seam — not through M8.

Two further shipped facts bound the experiment space:

- A **second blend spelling already exists**: the learnings seam
  (`packages/maistro-core/src/maistro/memory/learnings/embeddings.py`) blends
  `1.0 * keyword + 3.0 * embedding` with a 0.3 floor, while episodic sums the terms
  unweighted. The two canonical seams already disagree on how to combine the same two
  signals; a learned blend would be a third spelling unless the retrieval owner folds
  them together first.
- The working-log recall seam (`packages/maistro-core/src/maistro/memory/working/recall.py`,
  #301) is deliberately structural — lexical term overlap plus typed-lineage expansion,
  "never a learned embedding" by its own docstring. It is out of scope here and stays so
  unless a graduated reranker's owner explicitly extends it.

Embeddings reach retrieval through the ADR-079 model registry / `EmbeddingClient`
protocol. Downstream, the ranked list is consumed by the context-assembly budget
(ADR-091 / SPEC-244, `packages/maistro-core/src/maistro/memory/context_assembly.py`),
which is where recall/precision losses become answer-quality losses.

At this head nothing learned ships anywhere in retrieval: no reranker, no rewriter, no
cross-encoder, and no BM25/pg_trgm index (SPEC-243 names both as the lexical term's
eventual backing; neither exists — `keyword_overlap` is the shipped term).

## Record

No provider experiment exists: the deterministic CI environment holds no model
credentials, and no labeled Workspace retrieval corpus (graded relevance judgments) is
in-tree. Manufacturing one was out of scope, and absent evidence is recorded rather than
simulated (epic guardrail). What this leaf adds is the reproducible measurement machinery
the issue's benchmark demands, as evidence-only research code:
`packages/maistro-rsi/tests/test_m8c2_rerank_rewrite_benchmark_research.py` (26 checks).
It imports no maistro module — research evidence, never an authority (epic contract) —
and re-implements, for measurement only, the SPEC-243 formula, both shipped blend
spellings, the two-stage pool shape, a deterministic hashing embedder with a hand-authored
synonym-prototype surface standing in for `EmbeddingClient`, a rule-table rewriter
standing in for an LLM rewriter, pseudo-relevance-feedback expansion, and a
bigram-interaction stand-in for cross-encoder scoring — all against a pinned,
hand-checked corpus (34 scoped memories across 6 topics plus noise and two adversarial
high-weight memories; 12 queries with graded relevance, including two ambiguous
two-topic queries and a zero-lexical-overlap synonym probe).

Measured table (pinned corpus, k=3 and k=5, embedder "v1"; embeds = total embedding
calls across the 12-query run — production embeds query plus every candidate on every
retrieve, no cache):

| variant | R@3 | R@5 | P@5 | MRR | nDCG@5 | amb P@5 | adv top-5 | embeds |
|---|---|---|---|---|---|---|---|---|
| lexical_only (shipped, no client) | 0.39 | 0.45 | 0.43 | 0.88 | 0.701 | 0.50 | 9 | 0 |
| vector_only (issue's baseline) | 0.47 | 0.49 | 0.29 | 0.83 | 0.625 | 0.20 | 6 | 420 |
| hybrid 1:1 (shipped episodic) | 0.49 | 0.51 | 0.30 | 0.92 | 0.706 | 0.30 | 8 | 420 |
| hybrid 1:3 (shipped learnings) | 0.49 | 0.51 | 0.30 | 0.90 | 0.686 | 0.30 | 7 | 420 |
| hybrid 1:1, no ×weight (ablation) | 0.65 | 0.69 | 0.40 | 0.96 | 0.832 | 0.40 | 2 | 420 |
| two-stage, lexical recall + hybrid | 0.41 | 0.43 | 0.41 | 0.88 | 0.677 | 0.30 | 7 | 118 |
| two-stage, vector recall + hybrid | 0.49 | 0.51 | 0.30 | 0.92 | 0.706 | 0.30 | 8 | 589 |
| cross-encoder stand-in (pool) | 0.52 | 0.61 | 0.53 | 0.92 | 0.776 | 0.60 | 3 | 0 (+106 pair scores) |
| rewrite → hybrid | 0.65 | 0.72 | 0.41 | 0.96 | 0.831 | 0.50 | 4 | 420 |
| PRF expansion → hybrid | 0.52 | 0.58 | 0.30 | 0.78 | 0.630 | 0.30 | 7 | 840 |
| rewrite → PRF → hybrid | 0.67 | 0.78 | 0.42 | 0.79 | 0.714 | 0.50 | 4 | 840 |

("adv top-5" counts the two adversarial high-weight irrelevant memories appearing in any
top-5, summed over the 12 queries; "amb P@5" is precision@5 on the ambiguous slice only.)

These are mechanism findings on a synthetic hand-checked corpus, **not** evidence about
real models:

1. **Query rewriting is the strongest lever measured.** Rewrite-then-hybrid dominates the
   shipped hybrid on every quality cell at identical embed cost (R@5 0.51 → 0.72, nDCG@5
   0.706 → 0.831), because rewriting repairs vocabulary the lexical term cannot repair:
   it maps "rollback"/"undo" onto corpus terms and drops the stopwords
   `keyword_overlap` is structurally unable to ignore. It also rescues the zero-overlap
   failure class: "rollback the migration that locked the table" never reaches the revert
   memory (m3) under the shipped formula, and reaches it after rewriting.
2. **The ×weight term is the main adversarial amplifier on this corpus — and the shipped
   hybrid's biggest quality cost.** The weightless ablation beats the shipped formula on
   every cell (R@5 0.69 vs 0.51, nDCG@5 0.832 vs 0.706) while cutting adversarial top-5
   appearances from 8 to 2. The zero-overlap probe shows the same term from the other
   side: the vector term *finds* the relevant low-weight memory but the ×weight
   multiplication suppresses its bridge out of the top-5. Caveat that bounds this
   finding: production weights are produced by SPEC-240 reinforcement/decay, so weight
   correlates with usefulness there in a way pinned corpus weights do not model. The
   question "should retrieval multiply by weight at full strength" belongs to the
   retrieval owner (ADR-080), not to M8.
3. **PRF expansion without an embedding cache is the worst trade measured.** It doubles
   embed cost (840 vs 420) and *degrades* nDCG@5 (0.630 vs 0.706) and MRR (0.78 vs 0.92):
   round 1 inherits the high-weight-noise failure and expands the query with noise
   vocabulary. Expansion amplifies the first stage's failure mode; it does not correct
   it. Chained rewrite → PRF buys the best recall of any variant (R@5 0.78) at the worst
   MRR of the rewriting family (0.79) — recall buys precision down.
4. **The two-stage pool cut binds through the recall scorer, not only through pool
   size.** Lexical-recall-then-rerank loses recall at both k even where the pool (k=5 →
   50) exceeds the corpus (34), because the recall scorer drops every zero-overlap
   memory — exactly the matches only the vector term could find ("reranking cannot
   promote a memory the recall stage never returned", quantified: R@5 0.51 → 0.43).
   Vector recall loses nothing here but pays a full embed pass *plus* the rerank pass
   (589 embeds vs 420).
5. **The interaction (cross-encoder-shaped) scorer posts the best precision and the best
   ambiguous-slice precision (0.53 / 0.60) with zero embeds and embed-version immunity,
   but its recall stays below the weightless ablation's.** Its cost shape — pair scores
   scaling with pool size — is the cost a real cross-encoder would carry.
6. **Model-version sensitivity is real and concentrated exactly where embeddings are.**
   Swapping the embedder's version salt moves every embedding-consuming variant (mean
   top-5 agreement across queries for the shipped hybrid: 0.479; per-query as low as
   0.14), while the embed-free variants (lexical_only, the interaction scorer) are
   byte-identical across versions. Any learned reranker trained against one embedding
   version inherits exactly this exposure whenever the registry serves another.
7. **Robustness degrades monotonically under high-weight near-query noise.** Injecting
   noise memories whose tokens overlap the query drops q_deploy1 R@5 from 0.75 (clean) to
   0.25 at five injections; 25 flooding memories blind the two-stage lexical pool
   completely. Nothing reranking-shaped fixes a corpus that lets reinforcement weight
   noise to the top of the ladder — the fix is upstream in what earns weight.

Executed probe record (head 31d891a561, 2026-10-05):
`uv run pytest packages/maistro-rsi/tests/test_m8c2_rerank_rewrite_benchmark_research.py -q`
→ 26 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module.
Mutation checks: dropping the ×weight term, freezing the rewriter's substitution table,
and freezing the embedder's version salt each flip exactly the pins that name those
mechanisms — the pinned findings fail when their cause is removed.

## Benchmark procedure (what a real experiment must do)

1. Export a representative Workspace retrieval corpus with graded relevance: queries from
   session/outcome traces (ADR-017), relevance judged against the evidence that actually
   served answers, sliced to include ambiguous multi-topic queries and known-adversarial
   memories. Labels are the experiment; without them there is no experiment.
2. Run the shipped hybrid as baseline; run under it (a) vector-only, (b) each blend
   spelling, (c) rewrite-then-hybrid with a real LLM rewriter logging its own outputs,
   (d) PRF expansion with and without an embedding cache, (e) a real cross-encoder over
   the pool, (f) blend-weight sweep α ∈ [0,1] on (α·lexical + (1-α)·vector).
3. Measure the issue's full list per variant: Recall@k and precision@k (k=3,5,10),
   nDCG/MRR, downstream answer/task quality on a fixed judge set, wall-clock p50/p95
   latency, token/compute cost (embed calls, rewriter tokens, pair scores), ambiguous and
   noisy/adversarial slices, and model-version sensitivity by re-running under two
   registry-served embedding models.
4. Report the dominance frontier (quality vs latency vs cost) and the failure classes the
   winner still ships. Update this disposition with the numbers; route adoption to the
   SPEC-243/ADR-080 retrieval owner, including the SPEC-243 non-goal that must be opened
   first.

## Trust boundary

The harness is test-only code that imports no maistro module: it cannot become a second
memory authority (epic contract). No product code, flag, cache, or model call is added;
the canonical retrieval path is untouched. Any adoption — reranker, rewriter, blend
change, weight-term change — routes to the episodic retrieval owner, and a reranker that
reads weights or edits queries changes the SPEC-243 contract, so it needs that spec
amended, not a parallel implementation.

## Disposition

**WATCH.** Nothing here justifies a learned component in the canonical path today: there
is no labeled Workspace corpus, no provider experiment, and the pinned corpus warns that
the largest measured wins (rewriting, weight ablation) may shrink or invert once weight
is *earned* (SPEC-240) and embeddings are real. Record, however, the no-regret items the
retrieval owner can act on without any learned component, because the mechanisms they fix
are measured above:

- an embedding cache in `ScoredEpisodicRetrieval._vector_term` (production re-embeds
  every candidate on every retrieve; the measured cost of that is the 420-embed baseline
  and the 840-embed expansion);
- stopword handling in `keyword_overlap` (the lexical term's blind spot is measured, and
  rewriting buys quality partly by doing manually what a stopword list would do);
- the lexical recall scorer's zero-drop in the two-stage shape (measured recall ceiling
  independent of pool size).

Escalate to **INCUBATE** when a labeled corpus exists and a real experiment repeats the
rewrite win (or a cross-encoder precision win) at bounded latency/token cost on the
canonical seam; escalate to **REJECT** if the real experiment shows the wins were corpus
artifacts and the cost terms dominate. Model-version sensitivity must be part of any
INCUBATE evidence: a reranker coupled to one embedding version is a coupling to every
future registry change.
