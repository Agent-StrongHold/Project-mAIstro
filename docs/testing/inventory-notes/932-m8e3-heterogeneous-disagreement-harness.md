---
inventory-delta:
  packages/maistro-rsi/tests: +33
---
# 932 M8-E3: heterogeneous disagreement / verifier research harness (+33)

Issue #932 (leaf of epic #904, initiative #879) studies whether
heterogeneous-model disagreement and independent verifier judgments predict
errors better than repeated samples from one model (#930) or per-context
history (#931). No paired real-model corpus exists in deterministic CI, so the
research record stays honest (WATCH, synthetic-only evidence); this change
adds the leaf-specific measurement machinery the #932 benchmark procedure
needs, as one self-contained test module in `packages/maistro-rsi/tests/`
(`test_m8e3_heterogeneous_disagreement_research.py`, +33 node IDs).

The module loads the merged #904 harness from its test-module file by
`importlib` path (pytest's global `--import-mode=importlib` addopt keeps test
directories off `sys.path`, so a plain sibling import cannot resolve) — the
#930/#931 baselines in the comparison are the merged harness's own metric
implementations, not re-derivations. Like the merged harness it imports no
`maistro` module (asserted via AST), so no vulture/reachability identity moves.

The 33 cases validate, on deterministic hand-checked fixtures: per-family
correctness derived from ground truth rather than verdicts, with loud errors
for unknown families/primaries; signal projection carrying only present
evidence (single-family panels report constant maximum agreement — absence,
not confidence); correlated-error overlap P(both wrong)/P(either wrong) with
hand values and the undefined-when-neither-errs guard; joint error-rate
bounds; verifier confusion with hand-checked false-approval/false-rejection
rates and undefined-when-a-class-is-absent errors; convex signal combination
with degenerate-specification rejection; sequential self-consistency vs
parallel-panel cost/latency arithmetic (hand values, incremental ratio, and a
zero-baseline guard); a deterministic family-upgrade perturbation that fixes
only the target family (seed determinism, scope-leak mutation caught,
correlation reduction measured); and the comparative study itself — every
baselined signal scored on matched held-out tasks with one metric
implementation, disagreement and verifier each beating self-report, the
verifier separating errors on the agreeing (correlated) slice where
disagreement is blind by construction, and the convex ensemble strictly
dominating both single signals in AUROC plus risk-coverage.

Regression-sensitivity was checked by mutation: inverting the disagreement
signal (7 failures), swapping confusion rates (1), dropping combination
weights (1), inverting the judged outcome (6), and leaking the upgrade to all
families (1) all fail the suite.
