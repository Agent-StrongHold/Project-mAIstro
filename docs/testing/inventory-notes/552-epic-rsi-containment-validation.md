---
inventory-delta:
  packages/maistro-rsi/tests: +0
---

# 552 epic M5-B: RSI containment validation evidence (no new tests)

Validation-only lane for epic #552 at base c5e070d97. Zero production or test
changes; this note records executed evidence and the residual gaps that keep
the epic's convergence half open.

## Executed and passing (containment half)

- `uv run pytest packages/maistro-rsi/tests/test_no_host_shell_execution.py
  test_non_production_reachability.py test_quarantine.py test_promotion_review.py
  test_review_promotions.py test_sensitive_paths.py test_regression_judge.py
  test_run_model_arguments.py test_spec_conformance.py test_gate_helpers.py`
  — 141 passed. Pins: RSI is non-production-reachable (static import freeze on
  engine packages, Conductor confined to two policy-gated files); quarantine +
  signed approval gate promotion; sensitive-path protection; fail-closed
  regression judge; argv-only model arguments; SPEC §3 fail-closed conformance.
- `uv run pytest packages/maistro-rsi/tests/test_harvest_boundary.py
  test_export_policy.py test_autorun.py test_rate_pacer.py
  test_candidate_fitness.py test_test_inventory.py test_red_green_evidence.py
  test_evolve_bridge.py test_gateway.py test_quota_burn.py
  test_mutation_gate.py` — 211 passed.
- `uv run pytest packages/maistro-rsi/tests/test_run_rsi_isolated_wrapper.py
  test_harvest_entry_point.py test_harvest.py test_checkpoint_report.py`
  — 66 passed.
- `uv run pytest packages/hive-conductor/backend/tests/test_rsi_execution_containment.py
  test_rsi_review_decisions.py` — 61 passed. `rsi_execution_policy.py` is
  fail-closed on every default (no root ⇒ nothing authorized; shell profiles
  refused; unavailable isolation is an error, not a downgrade).
- `uv run ruff check packages/maistro-rsi` / `ruff format --check` — clean.
- Bandit gate is mandatory in fitness (`candidate_fitness.py` runs
  `python -m bandit` and emits `GateResult("no_bandit_high", ...)`); a missing
  or errored gate is a gate result, not a silent pass (#304). `TraceNote.gates`
  carries per-gate pass/fail with optional components omitted rather than
  reported as zeros (#820 evidence-derived summaries); CI-side execution
  evidence is `scripts/check-gates-ran.py` (#262 AC-2 semantics).

## Not proven (epic exit criteria still open)

- Canonical Run/NodeRun/Attempt convergence (#50): `grep` over
  `packages/maistro-rsi/src` and `packages/maistro-evolve/src` finds zero
  references to the canonical run seams. RSI campaigns are not yet canonical
  Runs; the child issue remains the blocker.
- Generic M3 BacklogItem/claim/campaign contract consumption (#98/#100/#101/#103):
  no contract imports anywhere in maistro-rsi; the only "backlog" hit is prompt
  text in `scout.py`.
- Shared M4 promotion-contract consumption: promotion currently consumes
  `maistro_evolve.improvement.ImprovementKind` and core RLPHD priors, but the
  shared candidate/evaluation/promotion contract required by the exit criteria
  is not demonstrably the one in use.
- Milestone re-parenting of children: GitHub hierarchy state, not verifiable
  from the repository.

Verdict recorded for the lane: containment proven, convergence unproven —
epic stays open pending #50 and the M3/M4 consumption children.
