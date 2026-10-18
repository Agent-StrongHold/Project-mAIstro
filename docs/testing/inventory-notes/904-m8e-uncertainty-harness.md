---
inventory-delta:
  packages/maistro-rsi/tests: +30
---
# 904 M8-E: uncertainty/calibration research harness (+30)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #904 (epic M8-E, initiative #879) asked for disciplined exploration of
uncertainty estimation, outcome-based calibration, abstention, and
confidence-aware escalation. No provider experiment exists yet, so the
research record (`docs/research/904-uncertainty-calibration-abstention.md`)
registers WATCH dispositions for all four leaves — and this change adds the
reproducible metric machinery the leaves' benchmark procedures need, as one
self-contained test module in `packages/maistro-rsi/tests/`
(`test_m8e_uncertainty_calibration_research.py`, +30 node IDs).

The module is deliberately test-side and imports nothing from `maistro`: it
is research evidence, not product code (M8 guardrails 1–2), so no vulture/
reachability identity changes. The 30 cases validate the metric math on
deterministic, hand-checked fixtures: ECE/Brier/reliability against worked
arithmetic (perfect calibration → ECE 0, constant overconfidence → 0.5,
top-edge binning of claimed 1.0), tie-aware AUROC extremes and the
single-class ValueError, tie-group-aware average precision degenerating to
prevalence, risk-coverage monotonicity with the full-outcome endpoint,
agreement/disagreement signal bounds with single-family absence reported as
0.0, Beta-prior shrinkage of thin contexts plus convergence to the observed
rate, a leakage-safe temporal split, hand-verified asymmetric-cost frontier
dominance (0.25 → 0.4 utility, unsafe rate 0.25 → 0.0), monotone
answer/defer rates, degenerate thresholds (always-answer and defer-
everything), overconfidence drift raising the unsafe rate of a fixed
self-report threshold while recalibrated scores absorb it, seed determinism,
and the evidence-only contract itself (frozen records, measurement-only
policy points, advisory marker).
