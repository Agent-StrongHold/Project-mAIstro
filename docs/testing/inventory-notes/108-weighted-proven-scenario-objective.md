---
inventory-delta:
  packages/maistro-evolve/tests: +24
  packages/maistro-rsi/tests: +8
---
# Weighted proven-scenario RSI fitness objective (#108, M5-B)

Adds the criticality-weighted proven-scenario objective as the initial scalar
objective of the RSI fitness, with contract/acceptance tests as the
non-negotiable correctness oracle.

- `packages/maistro-evolve` gains `scenario_objective.py` and
  `test_scenario_objective.py`: 24 tests pinning the criticality weight bands
  (cosmetic [1,2) < product [2,4) < security [4,8) — the tier ordering is
  structural, so cosmetic work can never outweigh product/security
  scenarios), objective/evaluation immutability and version+digest stamping,
  the literal weighted-aggregate arithmetic (renormalised over scored
  scenarios, clamped to [0,1]), correctness-failure-scores-zero, and the
  no-compensation rule (a security-scenario regression zeroes the scalar and
  vetoes promotion even while the raw weighted aggregate rises; unproven
  scenarios are not defended; tolerance absorbs noise but not regressions).
- `packages/maistro-rsi` gains `test_candidate_fitness_scenarios.py`: 8 tests
  pinning the Scorecard wiring — the `no_proven_scenario_regression` gate
  (absent evidence adds no gate), the dominant `proven_scenarios` signal, the
  default correctness oracle being the `tests_pass` gate (injectable for a
  broader security/contract oracle), gate detail recording correctness and
  the scalar separately, and a maxed-unrelated-signals candidate still
  vetoed to composite 0.0.
- `test_magnitude_pins.py`: the governed magnitude fixture
  (`governed_magnitudes_evolve.json`) is amended in lockstep with the
  production weight and ADR-070126-6386 (2026-10-03 amendment) —
  `proven_scenarios=0.50` becomes the max; `spec_completion=0.45` remains the
  largest work signal. One pin test is renamed to pin the new invariant pair;
  count for that suite is unchanged.

## Repair round (2026-10-03)

The repair round hardened the objective against two silent-failure modes and
records the suite counts the change actually adds (+24 / +8; the initial note
undercounted `test_candidate_fitness_scenarios.py` by one):

- a proven scenario id with historical evidence but **absent from the ruler**
  is `not_evaluated` and blocks promotion — a candidate cannot dodge a
  previously proven (e.g. security) scenario by leaving it out of the
  objective (`ScenarioOutcome.criticality`/`weight` are `None` for such
  rows); one test;
- non-finite scenario scores (NaN/±inf) are **rejected, not clamped to full
  credit** — `min(1.0, nan)` is `1.0` and `nan < x` is `False`, so an
  unguarded NaN measurement would score perfect and never count as a
  regression; four tests (3 parametrized + the comparison-side case);
- the objective digest serialises floats at full repr precision instead of
  rounding to 9 decimals, so near-boundary tolerances (e.g. `1e-10` vs
  `2e-10`, which can flip a regression verdict) always yield distinct
  digests; covered by the existing digest content-sensitivity test.
