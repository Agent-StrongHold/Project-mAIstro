---
inventory-delta:
  packages/maistro-rsi/tests: +50
---
# 931-m8e2-historical-calibration-harness

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #931 (M8-E2 leaf, epic #904) asked whether historical Run-outcome
evidence by task/model/tool context calibrates confidence better than
prompt-time self-report, measured over ECE, Brier, error discrimination,
data volume, drift sensitivity, subgroup calibration, and maintenance cost.
The epic-level harness (`test_m8e_uncertainty_calibration_research.py`)
already carries one Beta-smoothed history estimator plus the shared metric
math; this change adds the leaf's *comparative study* as one self-contained
test module, `test_m8e2_historical_calibration_research.py` (+50 node IDs),
which imports nothing from `maistro` (M8 guardrails 1–2: research evidence,
not product code, so no vulture/reachability identity changes).

The 50 cases cover: hand-checked ECE/Brier/AUROC/AUPRC arithmetic (perfect
calibration → ECE 0, constant overconfidence → 0.5, tie-group average
precision degenerating to prevalence); the order-preserving temporal split
with a leakage trap corpus where a fit that has seen the rows it is scored on
measures *better* than the honest train-only fit on those same rows
(stable across 200 corpus seeds); estimator families (frequency MLE,
Beta-Binomial posterior shrunk toward the pooled base rate, Platt scaling,
histogram-bin recalibration, and a 5-feature damped-Newton logistic over
self-report + history) against the raw-self-report and no-confidence
baselines on two opposite fixtures — history wins where context determines
skill, self-report wins where contexts share a base rate, and the logistic's
learned weights point at whichever signal the corpus actually supports;
shrinkage beating the MLE on thin interleaved contexts; Platt cutting the ECE
of inflated self-report ~3.5× while preserving AUROC exactly (monotone map);
a learning curve whose crossing of the self-report baseline defines the
volume threshold, with the `min_context_samples` floor capping thin-slice
damage at the no-confidence baseline and stopping to bind at volume; frozen
calibrators degrading under drift (Platt +0.25 overconfidence: ECE 0.079 →
0.105; base-rate shift stranding the frequency table, 0.329 frozen vs 0.099
refit on the drifted tail) with refit-on-the-drifted-window recovering;
subgroup reports exposing Simpson-style ECE cancellation that the aggregate
hides; an accurate per-estimator maintenance-cost ledger (stored floats,
context cardinality, train rows, retrain policy); and the evidence-only
contract (frozen records, plain [0,1] float predictions, advisory marker).

Six of the 50 postdate the first draft of this module and pin its solver
and context-axis corrections: the ridge penalty now enters the gradient of
the penalized objective as well as the Hessian (intercept excluded) in both
Platt scaling and the logistic, so coefficients converge to the penalized
optimum instead of drifting with the iteration count on near-separable
data — asserted by a 10-vs-1000-iteration coefficient-stability test that
fails against the Hessian-only variant; training rows of the logistic are
leave-one-out encoded so no row's history feature contains its own outcome
(pinned exactly for singleton and populated contexts, failing against a
full-table revert); and the context axes (task/model/tool) are estimator
configuration shared by fit and predict — four tests pin that the default
key pools toolsets while a tool-axis key separates them, that Bayes and the
logistic honor the same key, and that selecting an axis costs context
cardinality in the cost ledger.

Fixture numbers are deterministic but are assertions about the *machinery*
(comparisons and exact hand-computed values), never quoted as evidence about
real models — the disposition recorded in
`docs/research/931-historical-outcome-calibration.md` stays WATCH until the
study runs on a real exported outcome corpus.
