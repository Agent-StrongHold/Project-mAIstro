---
inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26-repair-verification (2026-10-05, head 4cdbb63d, repair round ebb5d3a6)

Focused validation round at the exact dispatch head `4cdbb63d9970` (base
`b3662bb3719a`). No production or test code changed, `inventory-delta: +0`.

## The open block resolves as publisher state, not tree state

The lane brief carried "CI gate failures: commit status not successful" and a
prior finding "Quality gate (Pillars 1–4, 7, 8) = failure" pinned to
`86144106d`. `86144106d` is an **ancestor** of the current head (an early
auto-26 merge point); the check-run snapshot captured in the dispatch context
at the exact head `4cdbb63d9970` shows every required check **success**,
including `Quality gate (Pillars 1–4, 7, 8)` and `exact-debt-ledger`. The two
`gates-ran` commit statuses at that head are `pending` (run 37281716203,
08:16Z — superseded) and `success` (run 37283096027, 08:28Z — newest). GitHub's
combined status reads the newest per context, so the head's commit status is
**successful**. Nothing repairable remains in the tree.

## Locally re-executed at this head (not trusted from the prior verify job)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass.
- `uv run pytest packages/maistro-registry/tests -q` — 66 passed.
- Registry-CI-exact invocation `pytest tests/tools/registry/
  tests/tools/test_lint_lifecycle.py packages/maistro-registry/tests
  --confcutdir=tests/tools -q` — 159 passed.
- `scripts/check-suite-inventory.py --suite packages/maistro-registry/tests`
  — ok: 66 identities = baseline 0 + deltas 61 (auto-26 notes) + 3 + 2
  (#1096 notes).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact vulture arguments) — 1338 reviewed
  identities = 1338 findings, all banked; no ledger amendment needed.
- `scripts/check-doc-links.py` — 0 broken relative links.
- `scripts/check-ac-state.py --ratchet --mandate origin/develop --run-tests`
  — "every criterion this change declares is proven"; chain mandate clean.
- `maistro-registry eval .` on the real corpus — recall@10 0.9583,
  MRR 0.9583, nDCG@10 0.930 over 24 golden queries; the declared no-answer
  query reports MISS (0.000 across all metrics) instead of a fabricated
  governing citation.
- `maistro-registry search "graph execution durable run noderun attempt" .
  --terms` — results carry full provenance (id, status, content version,
  path); the corpus-statistically rejected term (`run`) is reported.

## Acceptance criteria -> evidence

- Corpus pin + reviewable question/relevance set -> shipped
  `golden_queries.json` (24 queries: exact IDs, terminology, paraphrases,
  linked ACs, supersession, one declared no-answer) evaluated above.
- Lexical/BM25 baseline first; enrichment, expansion, term filtering compared
  separately on the same set -> README's measured table (MRR 0.958 baseline;
  term filter neutral, enrichment +0.021 MRR, broad expansion −0.27 MRR),
  with latency/cost stated.
- Exact source document/version resolution; enrichment cannot overwrite
  originals -> `IndexedDocument` carries the frozen `CorpusDocument`;
  provenance asserted in `test_retrieval_corpus.py`.
- Issue-named cases -> `test_renamed_source_keeps_stable_id_but_moves_the_fingerprint`,
  `test_version_changes_when_bytes_change`, `test_superseded_decision_is_retrieved_with_its_status`,
  `test_duplicate_identity_keeps_both_documents_addressable`,
  `test_expansion_terms_face_corpus_statistics`, no-answer MISS in
  `test_real_corpus_meets_the_recorded_quality_floor`.
- Stale index invalidation -> fingerprint enforced by `stale_index_reason`
  on every CLI `--index` use (`test_search_refuses_a_stale_saved_index`,
  `test_eval_refuses_an_index_stale_to_edited_content`), reproducible via
  `maistro-registry index`.
