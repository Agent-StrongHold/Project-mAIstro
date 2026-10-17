---
inventory-delta:
  packages/maistro-rsi/tests: +0
---

# 552 epic M5-B: RSI containment validation evidence (no new tests)

Validation-only lane for epic #552. First pass at base c5e070d97; re-validated
after merging origin/develop `ab8b3737f` (merge `6912141b0`, +364 commits of
child-issue work landed upstream). Zero production or test changes by this
lane; this note records executed evidence and the residual gaps that keep the
epic's convergence half open.

## Executed and passing at merged head 6912141b0 (containment half)

- `uv run pytest packages/maistro-rsi/tests/test_no_host_shell_execution.py
  test_non_production_reachability.py test_quarantine.py test_promotion_review.py
  test_review_promotions.py test_sensitive_paths.py test_regression_judge.py
  test_run_model_arguments.py test_spec_conformance.py test_gate_helpers.py`
  — **147 passed** (141 at first pass; the merge added containment-strength
  tests). Pins: RSI is non-production-reachable (static import freeze on
  engine packages, Conductor confined to two policy-gated files); quarantine +
  signed approval gate promotion; sensitive-path protection; fail-closed
  regression judge; argv-only model arguments; SPEC §3 fail-closed conformance.
- `uv run pytest packages/maistro-rsi/tests/test_harvest_boundary.py
  test_export_policy.py test_autorun.py test_rate_pacer.py
  test_candidate_fitness.py test_test_inventory.py test_red_green_evidence.py
  test_evolve_bridge.py test_gateway.py test_quota_burn.py
  test_mutation_gate.py` — **217 passed** (211 before).
- `uv run pytest packages/maistro-rsi/tests/test_run_rsi_isolated_wrapper.py
  test_harvest_entry_point.py test_harvest.py test_checkpoint_report.py`
  — **72 passed** (66 before).
- `uv run pytest packages/hive-conductor/backend/tests/test_rsi_execution_containment.py
  test_rsi_review_decisions.py` — **69 passed** (61 before).
  `rsi_execution_policy.py` is fail-closed on every default (no root ⇒ nothing
  authorized; shell profiles refused; unavailable isolation is an error, not a
  downgrade).
- New child-behavior work that landed upstream via the merge and passes here:
  `uv run pytest packages/maistro-rsi/tests/test_candidate_fitness_scenarios.py
  test_evaluator_immunity.py test_fail_first.py test_contained_fitness.py
  test_promotion_export_paths.py test_promotion_path_split.py
  test_gate_evidence.py test_intervention.py` — **220 passed, 3 skipped**
  (weighted proven-scenario fitness #108; evaluator/scenario/ratchet artifact
  protection #109; fail-first evidence #392; container-isolated fitness
  #2043; contained promotion patch exports + symlink-race refusal #2101;
  mechanical/judgment promotion split #110 partial).
- `uv run ruff check packages/maistro-rsi packages/maistro-evolve` — clean;
  `ruff format --check` — 254 files already formatted.
- Bandit gate remains mandatory in fitness (`candidate_fitness.py` runs
  `python -m bandit` and emits `GateResult("no_bandit_high", ...)`); a missing
  or errored gate is a gate result, not a silent pass (#304). `TraceNote.gates`
  carries per-gate pass/fail with optional components omitted rather than
  reported as zeros (#820 evidence-derived summaries); CI-side execution
  evidence is `scripts/check-gates-ran.py`.
- #804 non-instantiation: `grep -riE "workspace[_ ]agent|goal.?reconcil"
  packages/maistro-rsi/src` — zero hits; RSI does not instantiate or replace
  the persistent Workspace Agent/Goal reconciliation loop.

## Not proven at merged head (epic exit criteria still open)

- Canonical Run/NodeRun/Attempt convergence (#50, still open): `grep` over
  `packages/maistro-rsi/src` finds zero imports of canonical run seams — the
  only `runner` imports are RSI's own private `maistro_rsi.runner.RsiCycle*`
  (coordinator.py:35, autorun.py:75, cli.py:27, harness_adapter.py:38);
  `selfbranch.py:58` defines its own `SelfBranchAttempt`, not the canonical
  Attempt. maistro-evolve *has* converged partially — `tournament.py:46-111`
  treats canonical (node_run_id, attempt_id) as the idempotency key (#1064) —
  but RSI campaigns are still not canonical Run work.
- Generic M3 BacklogItem/claim/campaign contract consumption (#98/#100/#101/
  #103, #98 still open): a canonical substrate now exists —
  `maistro-core/src/maistro/workspaces/backlog_history/` (model, store,
  sqlite_store, recording, wiring) plus `maistro_server/api/backlog_history.py`
  — but `grep -rn "BacklogItem" packages/maistro-rsi/src` finds **zero**
  references; the only "backlog" hits remain prompt text (scout.py:46-64) and
  prose comments (autorun.py, intervention.py). RSI does not own a parallel
  system, but it also does not yet consume the generic one.
- Shared M4 promotion-contract consumption (#110 / M4-A, still open):
  `maistro_evolve.promotion` now exposes the shared substrate
  (`PromotionPolicy`, `selection_eligibility`, `promotion_eligibility`,
  `PromotionRecord`, `build_promotion_record` — promotion.py:87-418), and RSI
  consumes the evaluation half via `evolve_bridge.py:22-26,129`
  (`EvalHarness`, `PopulationStore`, `EvolutionCycle`, `evaluate_code_rsi`).
  But the RSI promotion path itself consumes only
  `maistro_evolve.improvement.ImprovementKind` (promotion_review.py:44) — the
  shared promotion-eligibility contract is not the one gating RSI promotions.
- Milestone re-parenting of children: GitHub hierarchy state, not verifiable
  from the repository.

Verdict recorded for the lane: containment proven (and re-proven after the
develop sync), convergence unproven — epic stays open pending #50 and the
M3/M4 consumption children.
