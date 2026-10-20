---
inventory-delta:
  packages/maistro-core/tests: +7
---

# M7-A7 — Evolve/RSI as consumers of the in-Run eval; no second loop (#796)

**+7 `packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py`** — static
contract tripwires that freeze the #796 map (M7 in-Run Rubric eval → M4 #21 evidence →
M5 #552 consumer) and fail the PR that stands a second design loop back up:

- `test_design_loop_does_not_import_rsi_or_evolve` — the Design Studio loop
  (`maistro_design` + the Hive `routes/design*.py` / `services/design*.py` surfaces)
  gains no static or dynamic (`importlib`/`__import__`/`find_spec`) import of
  `maistro_rsi`/`maistro_evolve`: the in-Run critic is maistro-core's Rubric eval,
  never RSI/Evolve. The dynamic half resolves the callable's local binding, so the
  builtin `__import__(...)` (a bare `ast.Name` call), `from importlib import
  import_module [as im]`, and `im = importlib.import_module` all trip — an
  attribute-only scan silently dropped the builtin form.
- `test_evolve_and_rsi_do_not_reach_the_design_rubric_domain` — no
  `maistro_evolve`/`maistro_rsi` module imports `maistro_design` or
  `maistro.personas`, so no fitness function can score design-Goal Rubric dimensions
  as a private metric. Import-based on purpose: benchmark corpora embed design
  strings as data; only an import is a live scoring path.
- `test_maistro_design_declares_no_scoring_or_promotion_surface` — `maistro_design`
  adds no score/eval/promote/fitness/critic/judge module, class or function: no
  private `maistro-design` promotion path; promotion stays #21's. Six
  definitions of #779's project-quality consistency evaluator and the pack
  upgrade preflight are banked by exact `(path, name)` identity
  (`_DESIGN_SURFACE_BANK`) — #779 is listed as Related in #796 and its
  evaluator is deterministic, read-only and "not a self-improvement authority";
  `_evaluate_upgrade` blocks on regressions and promotes nothing (the sixth
  row, `_evaluation_provenance`, is the provenance-citation helper #2204's
  #1663 complexity refactor extracted from the banked `evaluate_project_snapshot`,
  re-reviewed and re-banked in the PR that merged it). The bank is
  path-pinned (a banked name in a new module still trips) and self-ratcheting
  (a row whose code moved or vanished fails until re-reviewed), so any new
  scorer/evaluator/critic/promoter name in the package trips.
- `test_no_design_quality_scores_stored_outside_the_canonical_homes` — no
  `design_quality_score`-family identifier (assign/annotated/param/keyword/dict-key)
  appears in the Design Studio loop's own stores; Goal quality evidence lives only in
  Run eval records + M4 candidate evaluation.
- `test_the_one_eval_is_rubric_eval_in_core` — positive anchor: `RubricEval` still
  exists in `maistro/personas/rubric.py`, the engine the map names.
- `test_m5_rsi_nonproduction_pin_still_covers_the_design_loop` — the M5
  non-production-reachability suite still scans `maistro-design` as an engine package
  and still allowlists only the two Conductor RSI surfaces; trimming either would
  quietly open the second loop.
- `test_tripwires_catch_the_forbidden_shapes` — negative controls: every scanner is
  fed its forbidden shape in `tmp_path` (loop imports ×6 — two static plus four
  dynamic callable bindings, consumer imports ×2,
  scorer/promoter definitions ×3, score fields ×4, plus a banked def name at a
  different path to prove `_DESIGN_SURFACE_BANK` is path-pinned) and must catch all
  of them, so a green run on `develop` is a proven scan, not a vacuous one.

No production code changed; scans pass on `develop` as-is. The mapping prose lives in
`docs/architecture/CONVERGENCE-MATRIX.md` ("One scoring loop…"). Ownership untouched:
#21 (promotion), #552 (RSI), and the #990 fitness suite (product identity, lifecycle
names, provider egress) keep their scopes.
