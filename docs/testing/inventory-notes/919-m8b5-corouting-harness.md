---
inventory-delta:
  packages/maistro-rsi/tests: +30
---
# 919 M8-B5: prompt-model co-routing benchmark harness (+30)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #919 (epic #900, initiative #879) asked for an evaluation of prompt-model
co-routing and per-Agent/per-capability specialization. No provider experiment exists
— the deterministic CI has no credentials and no paired (item × model × template)
outcome corpus — so the research record
(`docs/research/919-prompt-model-co-routing.md`) registers WATCH and this change adds
the reproducible benchmark machinery the issue's measure list demands, as one
self-contained test module in `packages/maistro-rsi/tests/`
(`test_m8b5_corouting_benchmark_research.py`, +30 node IDs).

The module is deliberately test-side and imports no maistro module: it is research
evidence, not product code (M8 guardrails 1-2), so no vulture/reachability identity
changes. The 30 cases validate the accounting and the policy mechanics on
deterministic, hand-checked fixtures: pair cost math in `ModelMetadata` units with
template input tokens priced and a stated prefill-latency rule (exact cents/ms against
worked arithmetic, negative tokens rejected), catalog bounds and duplicate rejection,
the fixed-baseline judge reading only the served pair's own rows (never relabeled),
loud errors for missing cells / duplicate cells / inconsistent item labels, no-fit
roles falling back to the baseline pair with the fallback recorded, nearest-rank p95,
utility weights flipping the fitted choice deterministically with a lexicographic
tie-break, bound-1 catalog degenerating to the fixed baseline with identical
measurements but distinct fallback bookkeeping, maintenance-burden counting
(templates × active versions), the frozen 24-item grid record (byte-identical
reruns) where the fitted co-routing mapping routes the encoded
model×template interaction (14.4× cheaper than the baseline at validity 1.0) while
model-only ships structure failures (1/3) and prompt-only pays more than the baseline
(131.52¢) with tripled version surface, the family generalization gap (0.333) with
held-out success 8/12 vs baseline 1.0, the model-version-bump regret (0.282) and its
refit recovery, dead-catalog curation evidence, and the evidence-only contract itself
(advisory marker, no maistro imports via AST, empty-slice rejection).
