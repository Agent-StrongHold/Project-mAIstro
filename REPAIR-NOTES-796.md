# Repair/verification notes — #796 (M7-A7 eval-consumer map)

Lane `auto-796`, branch head `1f8ea45fca2c37876093268c2ca27b11f989e8cf`,
develop merge-base `f72d4fc921135dfe7df727c226fa6a29903c59af`. This note records
the independent verification of the repair commit `1f8ea45fc` ("bank #779
consistency-evaluator identities in the design-surface scan"), which resolved the
regression found in the previous round.

## What failed, and how it was resolved

The develop merge `d8a388bc2` brought `maistro_design/consistency.py` (#779
project-quality consistency evaluator) and the pack-upgrade preflight into the
tree after the M7-A7 contract test `88e3756ed` had landed. The def-name net in
`test_maistro_design_declares_no_scoring_or_promotion_surface` then flagged five
pre-existing definitions (prior-round evidence: job `a4e16c34…`,
`check-3.log` — `consistency.py:349,362,656,1039` + `packs/service.py:650`).
That failure is itself evidence the tripwire is live, not vacuous.

`1f8ea45fc` banked the five identities by exact `(relative_path, name)` in
`_DESIGN_SURFACE_BANK`
(`packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py:91`) and
kept the scan's strength: path-pinned rows, stale-row failure, and a negative
control proving a banked name at a different path still trips
(`test_tripwires_catch_the_forbidden_shapes`, impostor case at
`test_m7_a7_eval_consumer_map.py:531`).

## Banking review (the boundary judgment the previous round escalated)

Issue #796 lists #779 as **Related** and forbids exactly four shapes: an Evolve
fitness that invents a design-quality score for the same Goal; RSI mutating
Rubric/evaluator/fence policy; Design Studio calling Evolve/RSI as the in-Run
critic; a `maistro-design` private promotion path. None of the five banked
identities matches any of these:

- `consistency.py` pins its own contract in the module docstring:
  "Proposal, never mutation … no write path to any store"
  (`packages/maistro-design/src/maistro_design/consistency.py:19`), "deliberately
  deterministic … no model call" (`:10-11`), and "This is project-quality
  evaluation, not a self-improvement authority — historical evaluations may later
  become M4 evidence, but this module only evaluates and proposes for the current
  creative project" (`:35-38`). It is a *producer of evidence* — the map's
  consumer side — not a competing scoring authority.
- `evaluate_project_snapshot` (`consistency.py:1039`) is a pure function:
  "no store access, no mutation, no model calls" (`:1042`); it returns an
  in-memory `ConsistencyEvaluation` (verdict + findings + a proposal-only
  `RefinementProposal`), and stores nothing — so it cannot create a third home
  for a design-quality score either.
- `_evaluate_upgrade` (`packs/service.py:650`) is a read-only preflight returning
  `PackUpgradePreflight` with `can_upgrade=not blocked` (`:671`): it *blocks*
  upgrades on regressions/unauthorized backends/dropped rubric dimensions and
  promotes nothing. Promotion authority stays with #21.
- No banked identity imports `maistro_rsi`/`maistro_evolve` — tests 1-2 of the
  contract file pass, so none of them wires a second loop in.

Conclusion: banking these five is consistent with #796's forbidden list; the
module-name scan and the def-name net remain fully armed for anything else.

## Validation executed at `1f8ea45fc` (all green)

- `uv run pytest packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py -v` — 7/7 pass
  (including the previously failing surface test).
- `uv run pytest packages/maistro-core/tests/fitness/ -q` — 34/34 pass.
- `uv run pytest packages/maistro-rsi/tests/test_non_production_reachability.py -q` — 13/13 pass.
- `uv run pytest packages/maistro-design/tests -q` — 572 passed, 1 skipped.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run python scripts/check-convergence-matrix.py` — OK (52 subsystems / 1404 modules), exit 0.
- `uv run python scripts/check-suite-inventory.py` — ok (17 suites match), exit 0.
- `uv run python scripts/check-doc-links.py` — 0 broken links, exit 0.
- `uv run python scripts/check-contract-markers.py` — OK, exit 0.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) — exit 0, 1322 identities.
- `git merge-tree --write-tree HEAD origin/develop` — exit 0 (conflict-free); all
  five banked names still declared on `origin/develop` (develop's `d8675ac89`
  refactor kept them), so a future sync will not strand the bank.

## Residuals

- Acceptance criterion "PR is `feat/m7-a7-eval-consumer-map` off `develop`" is
  dispatcher-owned GitHub state; lane workers may not push or open PRs, so it is
  unverifiable locally by construction. The branch content itself is complete and
  green against the develop merge-base.
- The `(path, name)` bank is a documented boundary judgment. This note is the
  in-tree evidence dossier for that review; `_DESIGN_SURFACE_BANK`'s own
  docstring carries the same rationale at the point of use.
