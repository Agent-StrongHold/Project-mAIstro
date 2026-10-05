---
inventory-delta:
  packages/maistro-core/tests: +20
---

Adds coverage for the M4-B3 promotion evidence gate (`memory.learnings.evidence`): `promotion_blockers` refuses promotion without a source Run/evaluation ID, with unmeasured confidence, below the confidence floor, and for a counterfactual claim without an evaluation; the RCA extractor's LLM-distilled learning lands `EpistemicType.INFERRED` and cannot self-promote on hits alone (distillation is not validation evidence), yet promotes once a Run backs it and `mark_outcome` measures confidence; `InMemoryLearningStore.check_auto_promotions` and the `LearningPromoter` approval-gate path both honor the shared verdict and the `min_confidence` parameter.

Sixteen tests are new; the other four extend existing suites whose promotion fixtures assumed hits alone suffice: `test_learning_store.py` gains the no-evidence blocker case, `test_sqlite_learnings.py` gains refuse-without-evidence and refuse-majority-failing cases against the real SQLite path, and `test_pg_learnings.py` gains the unevidenced-candidate-stays-active case.
