---
inventory-delta:
  packages/maistro-core/tests: +27
---
# 118 — Gauntlet validation before collective knowledge promotion (M4-B2)

Twenty-seven new node IDs, all in `packages/maistro-core/tests`, in two files:

- `memory/learnings/test_gauntlet.py` (+23) — the `IndependentTrialsGauntlet`
  and its promoter wiring. The property under test is that local success alone
  (a threshold-crossing `hit_count`) cannot create shared institutional
  knowledge: the promoter with a `gauntlet=` configured promotes only
  candidates whose *independent* evaluation record passes producer
  attribution, frozen-content binding (`content_hash` must match the frozen
  candidate, so a verdict cannot be spent on mutated content), distinct
  canonical Run ids per trial, independence from the producing Run,
  held-out + multi-context + multi-regime coverage, declared applicability,
  and a minimum success rate. One end-to-end test drives trials through
  `RunExecutionService` (`Goal -> Graph -> Run -> NodeRun -> Attempt`) and
  asserts the promoted learning names exactly those Run ids, resolvable on
  the Run store. Rejection keeps the row `active` with its evidence intact
  (the anti-learning half) while `get_promoted` stays closed. The legacy
  no-gauntlet path and the gauntlet-over-approval-gate precedence are
  pinned so existing callers do not change behavior.
- `persistence/test_sqlite_learning_validation.py` (+4) — durability of the
  validation provenance on the SQLite twin: `promote_learning` writes
  `validated_by` / `validated_evaluator_version` / `validated_at` /
  `validation_run_ids` / `validation_content_hash`, refuses non-active and
  out-of-scope rows, round-trips the provenance across reads, and a
  pre-Gauntlet database upgrades in place with old rows reading as the
  never-validated learnings they honestly are.

Supporting changes folded into the same suites (no separate delta):
`promote_learning` delegation on `DurableHybridLearningStore` and
`HybridLearningStore` keeps the production wrappers conforming to the
extended `LearningStore` protocol (container.py assigns the former to a
`LearningStore`-typed name), and `test_pg_learnings.py`'s exact-insert-args
assertion gained the five new provenance columns in their never-validated
defaults.
