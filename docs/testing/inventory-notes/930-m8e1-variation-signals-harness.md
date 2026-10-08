---
inventory-delta:
  packages/maistro-rsi/tests: +35
---
# 930 M8-E1: variation-signal comparison harness (+35)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #930 (leaf M8-E1 of epic #904, initiative #879) asked for a comparison of
self-consistency, semantic entropy, and answer-variation signals as uncertainty
evidence. No provider corpus exists in deterministic CI, so the change is the
reproducible comparison machinery plus an honest WATCH record
(`docs/research/930-answer-variation-uncertainty-signals.md`), as one
self-contained test module in `packages/maistro-rsi/tests/`
(`test_m8e1_variation_uncertainty_research.py`, +35 node IDs). Like the epic
harness from #1958 it is test-side and imports nothing from `maistro` — a test
in the module asserts that on its own AST — so no vulture/reachability identity
changes.

The 35 cases validate: hand-checked signal math for self-consistency (modal
share), pairwise disagreement (with the disagreement + agreement-probability =
1 identity and a 5-sample hand value), distinct ratio, and semantic
entropy/confidence over pluggable equivalence clusters (synonym merging,
conservative default normalization, the equivalence function being load-bearing,
and the polysemy blind spot that identical strings cannot be split by any
string→id map); tie-aware AUROC extremes/single-class ValueError and
tie-grouped average precision degenerating to prevalence; signal-as-probability
ECE hand values; a deterministic temperature-/family-parameterized corpus
generator with mirage (confidently-wrong) tasks; the comparison table (sorted,
bounded, cost-carrying: sampled signals pay the k-fold bill, self-report 1);
the synonym-noise fixture where surface self-consistency sits at chance while
semantic clustering reaches AUROC 1.0; the mirage fixture where every signal
including agreement inverts below 0.5; temperature ordering (sharper samples
discriminate better; self-report as the unchanged control) and family
sensitivity; positive difficulty correlation; Spearman hand values with tie
averaging; cost/latency accounting (384 tokens at k=8, ceil-based parallel
latency, plus the recorded per-sample token/latency columns that distinguish
corpora with identical k but different measured per-call costs, and the
sampling-cost row for the registered `distinct_ratio` signal); and the
evidence-only contract (frozen records, measurement-only rows, advisory
marker, unknown-signal ValueError).

Two deltas over the first committed revision of this note (+33 → +35):
`test_temperature_limits_reach_uniform_and_modal_distributions` pins the
renormalized temperature transform's distributional limits (T → ∞ drives every
category — gold included — to a 0.25 share; T → 0 collapses sampling onto the
modal category, which is gold on the alpha family), and
`test_comparison_rows_carry_recorded_tokens_and_latency` pins the recorded
cost columns (a 48-token/100 ms corpus and a 480-token/10 s corpus must
produce different rows at the same k). The same revision registers
`distinct_ratio` in the comparison table against an independently written-down
`EXPECTED_SIGNALS` set, so a future register omission fails instead of
comparing the output against the register it came from.
