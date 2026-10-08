# M8-E2 research note — calibrating model and Agent confidence from historical Run outcomes

Leaf [#931](https://github.com/Agent-StrongHold/Project-mAIstro/issues/931) (epic
[#904](https://github.com/Agent-StrongHold/Project-mAIstro/issues/904), initiative
[#879](https://github.com/Agent-StrongHold/Project-mAIstro/issues/879)). Sibling leaves:
[#930](https://github.com/Agent-StrongHold/Project-mAIstro/issues/930) (variation signals —
see the epic note), [#932](https://github.com/Agent-StrongHold/Project-mAIstro/issues/932)
(heterogeneous disagreement — see the epic note).

## Hypothesis

Historical success/failure evidence by task/model/tool context can produce better calibrated
confidence estimates than prompt-time self-report alone.

## Canonical seams

The outcome seam is the canonical (context, outcome) record: the ADR-017 outcome store
(`packages/maistro-core/src/maistro/memory/outcomes.py`, row shape in
`packages/maistro-core/src/maistro/types/memory.py::Outcome`) has columns for `task_type`,
`model_used`, tool-call presence, and the observed `success` bit per completed Run — the
context axes this leaf conditions on. **Known gap:** the only production `Outcome` writer
(`packages/maistro-core/src/maistro/agents/base.py`) currently stores `task_type=""`, so a
naive export collapses all Runs into one empty task family. Populating that column (from the
agent's already-classified `classified_task_type` at the same seam) or joining it via
`run_id` is a hard prerequisite for step 1 of the benchmark procedure below; until then the
task-conditioned subgroup and context-volume results are fixture-only. The prompt-time self-reported confidence is the
signal to be judged; it is not part of the row today, so a real experiment attaches it at the
prompt boundary and joins on the Run. Governed inference — where any adopted calibrated score
would eventually have to act — runs through Binding → Invocation → the single approved gateway
provider; routing authority lives in `CostAwareRouter`, escalation authority in the canonical
Warden/HITL/delegation controls (ADR-068).

One adjacent seam is deliberately NOT reused: `maistro_evolve.benchmarks.calibration`
calibrates *proxy scorers for genome tournaments* against their own grading — a different
estimand from calibrating model/Agent confidence against observed task outcomes.

## What exists now

The epic note's harness (`packages/maistro-rsi/tests/test_m8e_uncertainty_calibration_research.py`)
provides one Beta-smoothed history estimator and the shared metric math. This leaf adds the
comparative study the leaf text defines, as a self-contained test-side module
(`packages/maistro-rsi/tests/test_m8e2_historical_calibration_research.py`, 50 node IDs, no
`maistro` imports):

- **Estimator families fit on a chronological train split only**: frequency (per-context MLE
  with a `min_context_samples` floor), Bayesian (Beta-Binomial posterior shrunk toward the
  pooled base rate — empirical-Bayes, so an imbalanced corpus is not shrunk toward 0.5),
  Platt scaling (parametric recalibration of the self-report), histogram-bin recalibration
  (nonparametric), and a logistic model over [bias, self-report, history rate, experience
  mass, self-report × history] fitted by damped Newton (IRLS) with a ridge penalty;
- **Baselines**: raw self-report and no-confidence (pooled train base rate);
- **Measures**: ECE, Brier, error AUROC/AUPRC, per-size learning curves, overconfidence and
  base-rate drift perturbations, per-subgroup ECE/Brier with worst-group reporting, and a
  per-estimator maintenance-cost ledger (stored floats, context cardinality, train rows,
  retrain policy);
- **Leakage guard**: an order-preserving temporal split is the only split the study exposes,
  and a reversal corpus demonstrates why — a fit that has seen the rows it is scored on
  (train+test) measures *better* than the honest train-only fit on those same rows, so a
  shuffled or future-leaking split inflates every comparison.

## Fixture findings (machinery validation, NOT real-model evidence)

No provider outcome corpus exists in this repository's deterministic CI, and manufacturing one
was out of scope (M8 guardrail 3: absent evidence is recorded, not simulated). What the
deterministic fixtures do establish — as validated behavior of the study machinery, with every
comparison asserted in tests:

- **History beats self-report exactly when context determines skill.** On the
  history-informative fixture (four task families spanning success rates 0.2–0.9, two model
  families, self-report a noisy proxy with σ≈0.22), held-out Brier improves 0.219
  (self-report) → 0.177 (frequency and Beta posterior), and error AUROC/AUPRC improve with it.
  On the control fixture where every context shares one base rate and the self-report is
  sharp, history collapses to the no-confidence baseline and the self-report wins — the
  estimator ranking inverts exactly as the hypothesis predicts, so neither signal is
  categorically superior.
- **The logistic model reads out which signal the data supports.** Its learned history weight
  dominates on the first fixture (3.45 vs 0.22) and the ordering reverses on the control
  (self-report 2.56 vs history −0.22) — a built-in diagnostic for the real-corpus run.
- **Shrinkage earns its keep on thin contexts.** With ~3 rows per context, the Beta posterior
  (prior 5) beats the MLE on held-out Brier (0.225 vs 0.250) and converges to it as data
  grows (< 0.03 max gap at scale).
- **Recalibration fixes miscalibration without touching discrimination.** Platt scaling cuts
  the ECE of an inflated self-report (inflation 0.30) by more than half while leaving AUROC
  bit-identical (a monotone map), and stays harmless on an honest self-report.
- **Data volume has a real threshold.** At 1 row per context the MLE's held-out Brier is
  0.339 — far worse than doing nothing (0.250); the crossing of the self-report baseline sits
  between 1 and 2 rows per context on this fixture (8 → 16 total rows across its eight
  task/model families: 0.339 → 0.217 against a 0.219 baseline), and quality keeps improving
  to 0.177 at 150 rows per context. The `min_context_samples` floor caps thin-slice damage at
  the no-confidence baseline and stops binding at volume — the knob a production system would
  ship with.
- **Frozen calibrators rot.** A +0.25 overconfidence drift raises a frozen Platt model's ECE
  roughly a third (0.079 → 0.105); refitting on the drifted window recovers most of the gap
  (0.082). A 50% late-window base-rate shift hits much harder: it strands the frozen
  frequency table (0.184 → 0.252 on the mixed window; 0.329 vs 0.099 for frozen vs refit on
  the fully drifted tail — a 3× gap). Retraining discipline is not optional — it is the
  dominant maintenance cost.
- **Aggregate calibration hides the worst subgroup.** Two families with opposite-signed
  miscalibration sharing one self-report bin produce aggregate ECE ≈ 0 while each family sits
  0.2 off; the subgroup report is mandatory reading, not a nice-to-have.
- **Context cardinality is the state-explosion hazard.** The cost ledger scales linearly with
  tracked contexts (one float each), and high-cardinality deployments thin every cell below
  the reliability floor — forcing either shrinkage or the fallback knob.

## Benchmark procedure (the real experiment, when an outcome corpus exists)

1. Export judged Runs from the outcome seam: (task family, model family, toolset,
   self-reported confidence, observed outcome, arrival order), joining the self-report at the
   prompt boundary. Prerequisite: a non-degenerate task-family source — the production
   writer must populate `task_type` (e.g. from `classified_task_type`) or the export must
   join it, else per-task-family conditioning is impossible.
2. Split with `m8e2_temporal_split`; fit every estimator on the earlier split only.
3. Score every estimator against both baselines on the held-out split: ECE, Brier, error
   AUROC/AUPRC, plus per-task-family and per-model-family subgroup reports.
4. Read the learning curve for the volume threshold (the corpus size at which each estimator
   first beats the self-report baseline) and the weights of the logistic model for which
   signal the data supports.
5. Re-measure under the overconfidence and base-rate drift perturbations; report the frozen
   vs refit gap as the retraining cost, and the threshold-crossing age as the staleness
   window.
6. Cost accounting must include fitted-state size, context cardinality, and the retraining
   cadence — not only accuracy.

## Trust boundary

Confidence remains advisory until separately adopted. The estimators return plain floats in
[0, 1]; nothing in the harness reads or writes a Goal, a Run authority, a routing decision, or
a Warden/HITL/delegation control, and every record is a frozen dataclass. Any future adoption
(calibrated scores informing `CostAwareRouter` or a HITL prompt) routes through the earliest
owning milestone and the canonical authorization paths (ADR-068); a calibrated score may
*inform* a decision, never substitute for one.

## Disposition

**WATCH** — the study machinery, leakage guard, and maintenance-cost ledger exist and are
validated on deterministic fixtures, but no real-model outcome corpus has been run through
them, so the hypothesis is untested on MAIstro workloads.

- **Move to INCUBATE** when: `task_type` is populated for exported Runs (the empty-string
  collapse above is fixed at the writer or repaired by join), and the benchmark procedure
  above runs on a real exported outcome corpus of sufficient volume (learning-curve crossing reached — on the fixture, a couple of rows
  per context; the real threshold is measured, not assumed), and at least one learned
  estimator beats the raw self-report baseline on held-out ECE *and* Brier at acceptable
  drift-refit cadence and state size.
- **REJECT** if: the held-out improvement never materializes at real corpus volume; subgroup
  (task-family) calibration is too unstable for a single shared table and per-family
  recalibration exceeds the maintenance budget; or the outcome seam proves unable to join
  self-reports to outcomes reliably (the feature the whole study conditions on).
- Adoption of any calibrated score remains a separate, explicitly owned production change;
  this leaf delivers evidence and machinery only.

The epic note's per-leaf disposition table points here; the epic stays open until each leaf
records a terminal disposition.
