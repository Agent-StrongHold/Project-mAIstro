---
inventory-delta:
  packages/maistro-registry/tests: +1
---
# auto-26 duplicate-identity metric guard

Repair round for the auto-26 lane (issue #26, corpus-aware architectural
retrieval): the prior verification round demonstrated that on the
duplicate-identity corpus — two files claiming one registry id, exactly
the corpus state the issue requires to stay addressable — `evaluate()`
reported recall=2.0 and nDCG@10=1.63, because `_evaluate_case` fed the
raw per-result ranking (same doc id at two ranks) to `recall_at_k`,
`ndcg_at_k`, and `matched_relevant` without reducing it to identities.

## packages/maistro-registry/tests: +1

`test_duplicate_identity_keeps_metrics_within_bounds` in
`test_retrieval_quality.py` builds the same five-document duplicate-id
corpus the corpus-side addressability test uses, runs it through the
real searcher and `evaluate()`, and asserts the measured ranking is
per-doc-id (first occurrences only), every per-query metric stays
within its theoretical maximum, and a fully-relevant duplicate hit
measures recall=1.0 / nDCG=1.0 with `matched_relevant` naming the id
once. The guard was shown failing against the pre-fix head (515a0284)
with exactly the reported recall=2.0 / ndcg=1.63 values before the
`quality.py` reduction was added.

The production change is one line of measurement-layer hygiene in
`_evaluate_case` (`dict.fromkeys` reduction); the search layer is
untouched — both claimants remain addressable with distinct paths and
content versions, per `test_duplicate_identity_keeps_both_documents_addressable`.
