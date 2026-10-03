# maistro-registry

Validates ADR/spec front matter, checks cross-references, and generates the canonical registry (ADR-031). Installed as the `maistro-registry` console script from the workspace root.

## Corpus-aware retrieval (issue #26 / EPIC M4-F)

ADR/spec/AC/incident/known-gap retrieval is lexical (BM25), corpus-aware,
and *measured* — deliberately before any vector infrastructure. The
pipeline lives in `maistro_registry/retrieval/`:

- **`corpus.py`** — provenance-carrying retrieval units: front-matter
  ADRs/specs (validated fields only; broken front matter degrades to
  body-only indexing instead of darkening the corpus) plus
  `KNOWN-GAPS.md` split into one unit per `### ` section. Every unit
  carries path, id, status, and a short content hash (`version`), and
  every search result returns that record whole.
- **`terms.py`** — tokenization (lowercase alphanumeric runs, light
  trailing-s normalization, structural endings guarded) and corpus
  statistics. **Useless-term rejection is measured, not enumerated**:
  a query term is dropped when the corpus has never seen it or when its
  document-frequency share reaches the ceiling (default 0.5 — measured
  on this corpus: "spec" 0.73, "adr" 0.85, "the" 0.99 are glue; "canvas"
  0.12, "retrieval" 0.05 are topics). Rejected terms are reported back
  in every response.
- **`index.py`** — offline document enrichment (title ×3, headings and
  id/slug/layer keywords ×2, body ×1 — a field-weighted BM25
  approximation) and the serializable index. A saved index carries a
  corpus fingerprint over (path, version) pairs and refuses to load
  under a foreign format version.
- **`expand.py`** — optional LLM query expansion sent through the one
  governed model-egress seam (`execute_model_chat` in
  `maistro.capabilities.providers.llm_gateway`, the module
  `quality/model-egress.json` approves; no second HTTP road to a model
  endpoint). The expander raises on failure; the searcher catches,
  reports `expansion_skipped`, and proceeds lexical-only. Expansion
  output is candidate terms that corpus statistics can still veto — the
  corpus, not the model, has the last word.
- **`search.py`** — the pipeline: tokenize → reject useless terms →
  expand → Okapi BM25 → deterministic rank (score desc, path asc).
- **`quality.py`** — graded golden queries (3 = direct, 2 = strong,
  1 = related), recall@k / MRR / nDCG@k, and threshold-capable
  evaluation.

### CLI

```bash
maistro-registry search "canvas publish export pptx" . -k 5
maistro-registry search "task queue restart" . --terms   # show what each result matched
maistro-registry search "task queue restart" . \
  --expand-endpoint http://localhost:4000 --expand-model gpt-4o-mini
maistro-registry index . --output registry/retrieval-index.json
maistro-registry search "alembic" . --index registry/retrieval-index.json
maistro-registry eval . --min-mrr 0.9 --min-recall 0.9   # exit 1 below threshold
maistro-registry eval . --json                           # machine-readable report for artifacts
```

Expansion endpoint roots are OpenAI-compatible API roots (a missing
`/v1` is appended for you); the credential travels on the gateway
endpoint only, never in the request payload.

`eval` without `--golden` uses the shipped golden set
(`maistro_registry/retrieval/golden_queries.json`), which encodes which
documents of *this* repository answer *this* repository's architectural
questions — exact ids, terminology, paraphrases, decision/spec linkage,
supersession pairs, and one declared no-answer case. Measured at
authoring time over that set at k=10: **MRR 0.958, recall@10 0.958,
nDCG@10 0.930** (the only misses belong to the no-answer case, by
design). The same floor is asserted by
`packages/maistro-registry/tests/test_retrieval_quality.py`; if it
fails, read the per-query report (`maistro-registry eval .`) before
touching anything — the report names the missed documents.

### Measured comparison on the one golden set (corpus @ 2026-10-03,
432 documents, 24 queries)

Each intervention measured separately against the same golden set and
the same corpus state — the numbers a regression has to beat, not
examples:

| Variant | MRR | recall@10 | nDCG@10 |
|---|---|---|---|
| shipped baseline (enrichment + term filtering, no expansion) | 0.958 | 0.958 | 0.930 |
| term filtering disabled (`--max-df-share 1.0`) | 0.958 | 0.958 | 0.931 |
| offline enrichment disabled (body terms only) | 0.938 | 0.958 | 0.916 |
| + static expansion candidates (untopicalized) | 0.689 | 0.854 | 0.701 |

Reading, honestly: the corpus-statistical filter is *neutral* on this
golden set (+0.001 nDCG without it) — its value is robustness to glue
terms the set only partly stresses ("the", "run", "by"), not a measured
gain here. Enrichment is worth +0.021 MRR: one more query finds its
document at rank 1 with it. Expansion candidates help only when they
name the right synonyms — broad candidates *cost* 0.27 MRR even though
every one of them was a corpus word the statistics could not veto,
which is why expansion is opt-in and off by default.

Latency/cost on the same machine: index build ≈ 0.3 s for 432
documents, ≈ 2 ms per query, zero network. Expansion adds one
governed chat call per query (temperature 0, `max_tokens` 200) and one
network round trip; its latency is whatever the gateway's is and is
*not* measured offline — the `expansion_skipped` discipline exists so
that cost is always visible instead of assumed.

No new external dependencies were added (ADR-039 substrate posture):
the baseline is stdlib + pyyaml/pydantic/httpx, all pre-existing.
