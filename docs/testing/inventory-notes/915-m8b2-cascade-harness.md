---
inventory-delta:
  packages/maistro-rsi/tests: +37
---
# 915 M8-B2: cascade benchmark harness (+37)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #915 (epic #900, initiative #879) asked for an evaluation of cheap-model-first
cascades with confidence-triggered escalation. No provider experiment exists — the
deterministic CI has no credentials and no paired (cheap, strong) outcome corpus — so
the research record (`docs/research/915-cheap-model-first-cascades.md`) registers WATCH
and this change adds the reproducible benchmark machinery the issue's measure list
demands, as one self-contained test module in `packages/maistro-rsi/tests/`
(`test_m8b2_cascade_benchmark_research.py`, +37 node IDs).

The module is deliberately test-side and imports no maistro module: it is research
evidence, not product code (M8 guardrails 1-2), so no vulture/reachability identity
changes. The 37 cases validate the accounting and the policy mechanics on deterministic,
hand-checked fixtures: tier cost math in `ModelMetadata` units with the escalated-pays-
both-tiers and provider-error-bills-nothing rules (exact cents against worked
arithmetic), the fixed strong baseline (57.5¢) with mean/p95 latency, a tuned cascade
costing 16.15¢ at equal quality versus a low threshold shipping exactly one
overconfident failure (quality 2/3), the always-escalate degenerate equaling baseline
plus sunk cheap spend (58.65¢), strict threshold comparison at the boundary, escalation
rate / false-confidence / quality / cost monotonicity across a threshold grid,
unnecessary-escalation counting, both provider-error handling policies, Beta-smoothed
historical calibration with its leakage rule and global fallback (hand value 1/3),
loud errors for absent #904 signals, sweep uniqueness/ordering with a deterministic
utility tie-break, stated-cost weights flipping the chosen threshold, the 240-item
two-regime fixture where a discriminating verifier signal dominates the baseline
(825.6¢ vs 2280¢ at equal quality) while self-report either ships 14 false-confidence
failures or escalates everything, and the evidence-only contract itself (advisory
marker, frozen records, measurement-only outputs, no maistro imports via AST, empty-
corpus rejection).
