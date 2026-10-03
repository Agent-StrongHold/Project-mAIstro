---
inventory-delta:
  packages/maistro-evolve/tests: +19
  packages/maistro-rsi/tests: +7
---
# Weighted proven-scenario RSI fitness objective (#108, M5-B)

Adds the criticality-weighted proven-scenario objective as the initial scalar
objective of the RSI fitness, with contract/acceptance tests as the
non-negotiable correctness oracle.

- `packages/maistro-evolve` gains `scenario_objective.py` and
  `test_scenario_objective.py`: 19 tests pinning the criticality weight bands
  (cosmetic [1,2) < product [2,4) < security [4,8) — the tier ordering is
  structural, so cosmetic work can never outweigh product/security
  scenarios), objective/evaluation immutability and version+digest stamping,
  the literal weighted-aggregate arithmetic (renormalised over scored
  scenarios, clamped to [0,1]), correctness-failure-scores-zero, and the
  no-compensation rule (a security-scenario regression zeroes the scalar and
  vetoes promotion even while the raw weighted aggregate rises; unproven
  scenarios are not defended; tolerance absorbs noise but not regressions).
- `packages/maistro-rsi` gains `test_candidate_fitness_scenarios.py`: 7 tests
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
