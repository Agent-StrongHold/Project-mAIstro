---
inventory-delta:
  packages/maistro-core/tests: 0
---

# M4-B5 + M4-B3 develop integrations (merges of 35f2e0158 and origin/develop
into auto-118) — test reconciliation

This merge resolves the collision between this branch's independent-trials
Gauntlet (M4-B2, #118) and develop's M4-B5 umbrella (#1753, ADR-100126-8c2d),
which landed its own #118 outcome-evidence Gauntlet plus the lifecycle
epistemics (#117/#119/#120/#121) on the same seam. Net suite count is
unchanged: the union preserves every test node from both sides.

Reconciliations that touched tests:

- `test_gauntlet.py` — both sides added the file. The merged file keeps this
  branch's 55 independent-trials/promoter tests and appends develop's classes
  (`TestEvidenceProjection`, `TestOutcomeEvidenceGauntlet`, `TestChainedGauntlet`,
  `TestPromoterWithGauntlet`, `TestCaptureAntiPatterns`,
  `TestAntiPatternKnowledgeReuse`), adapted to the merged `LearningGauntlet`
  protocol: `evaluate(learning)` builds its own evidence projection, so
  develop's `evaluate(lr, evidence=evidence_of(lr))` calls drop the kwarg.
  Develop's `test_gauntlet_takes_precedence_over_approval_gate` is kept; this
  branch's module-level `test_gauntlet_takes_precedence_over_the_approval_gate`
  covers the same posture for the independent-trials Gauntlet.
- `test_pg_learnings.py` / `test_pg_learning_stage.py` — the INSERT-shape
  assertions now pin the union write: the Gauntlet provenance columns
  (`validated_by`, `validated_evaluator_version`, `validated_at`,
  `validation_run_ids`, `validation_content_hash`) beside the lifecycle
  epistemics columns, 35 bound parameters in dataclass order.
- `test_sqlite_learning_validation.py` — `validated_at` asserts move from
  epoch floats to the ladder's `datetime | None` shape (a null names no
  instant; the column is owned by `053_learning_lifecycle_columns`); the
  fixture constructs the store with an ADR-057 exposure mode.
- `tests/migrations/test_capability_invocation_effect_index_migration.py` —
  the chain walk pins one linear head again: `057_learning_validation_
  provenance` re-parents onto develop's tip (`056_user_model_facts`, past
  `053_learning_lifecycle_columns`, `054_learning_applicability_epistemics`,
  `055_task_admission_generations` and `043_invocation_quota_door`).
- The full-develop sync additionally adopts ADR-057 (write authority): every
  store construction in the Gauntlet suites now declares
  `exposure_mode=MemoryExposureMode.AGENT_MANAGED`, and the legacy-path tests
  carry the source Run and measured confidence the M4-B3 evidence contract
  requires, so they keep isolating exactly the ceremony the legacy path skips.

Semantics unified by the merge (code, pinned by the above tests):
`Learning.validated_at` is the ladder's nullable instant everywhere (ADR
design on develop); this branch's provenance extras — evaluator version,
evaluation Run ids, frozen-content hash — are carried by renumbered migration
`054` and both SQL twins, and `promote_learning` now walks the ladder
atomically (a promoted row is a `repertoire` row in both reads).
