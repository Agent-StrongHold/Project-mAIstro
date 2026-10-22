# M8-E research note — uncertainty, calibration, abstention, and confidence-aware escalation

Epic: #904. Leaves: #930, #931, #932, #933. Initiative: #879. Cross-referenced: #915 (M8-B2
cascade escalation consumes these signals).

## Research question

Can MAIstro estimate when an Agent/model is likely wrong well enough to improve routing,
delegation, human escalation, and verification decisions?

## Canonical seams

Confidence signals must be *judged*, and judgment needs outcome ground truth. The canonical
outcome seam is the outcome store (ADR-017,
`packages/maistro-core/src/maistro/memory/outcomes.py`, with the SQLite/Postgres projections
under `packages/maistro-core/src/maistro/persistence/`): it records task outcomes per model and
context, which is exactly the (context, self-report, observed outcome) shape leaf #931 needs.
Governed inference — where any sampled or logprob-based signal would originate — runs through
Binding → Invocation → the single approved gateway provider
(`packages/maistro-core/src/maistro/capabilities/model_chat.py`,
`packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`). Routing authority
lives in `CostAwareRouter` (`packages/maistro-core/src/maistro/providers/router.py`); human
escalation authority lives in the canonical Warden/HITL/delegation controls
(`packages/maistro-core/src/maistro/security/warden/`,
`packages/maistro-core/src/maistro/graph/durable_runs/hitl.py`, ADR-068).

One adjacent seam already exists and is deliberately NOT reused:
`packages/maistro-evolve/src/maistro_evolve/benchmarks/calibration.py` calibrates *proxy
scorers for genome tournaments* against their own grading, not model/Agent confidence against
observed task outcomes. Different estimand; M8-E must not borrow its fixtures or its authority
story.

## Record

This note does not report a provider experiment. No real-model corpus exists in this
repository's deterministic CI, and manufacturing one was out of scope; absent evidence is
recorded rather than simulated (M8 guardrail 3). This change adds no product code, no feature
flag, and touches no authority path.

What this change adds is the reproducible metric machinery the leaves' benchmark procedure
requires, as clearly separated research artifacts:
`packages/maistro-rsi/tests/test_m8e_uncertainty_calibration_research.py` (test suite only; it
imports nothing from `maistro`, so it cannot become an authority by accident — M8 guardrails 1
and 2), plus the #932-specific companion below. Validated on deterministic, hand-checked
synthetic fixtures, the merged harness implements:

- calibration against observed outcomes: ECE, Brier score, reliability curve (the epic's
  contract sentence, enforced in code — self-report is one signal, the outcome is the judge);
- discrimination: tie-aware AUROC, tie-group-aware average precision, risk-coverage/AURC;
- variation signals (#930): sample-agreement score (1 − normalized entropy of the answer
  multiset) as an embedding-free stand-in for the self-consistency / semantic-entropy family;
- heterogeneous disagreement (#932): pairwise cross-family disagreement, with a single family
  reported as *absent evidence* (0.0), never as confidence;
- historical calibration (#931): per-context Beta-smoothed success rates, an order-preserving
  temporal split (leakage guard), and an explicit self-report/history blend;
- policy evaluation (#933): the answer-vs-defer utility frontier (expected utility, unsafe
  action rate, defer rate, unnecessary-deferral rate) under stated costs, plus an
  overconfidence-drift perturbation for threshold-robustness measurement;
- escalation destinations (#933): a destination-aware frontier (`EscalationDestination`,
  `m8e_route_to_destination`, `m8e_escalation_frontier`) that routes deferred decisions by
  confidence band to the leaf's four destination classes — stronger model, specialist Agent,
  verifier, HITL — and reports expected utility, unsafe-action rate, escalation rate,
  human-intervention rate, unnecessary-escalation rate, mean escalation cost, and mean
  escalation latency per threshold. Destination success rates, costs, and latencies are
  operator-supplied measurements (cascade/outcome data, #915), never invented by the harness;
  the frontier computes expected utility under stated parameters and never acts.

The harness also demonstrates — on synthetic data only — the comparison the leaves must run on
real data: a disagreement-family signal outranking self-report as an error predictor
(AUROC 1.0 vs 0.0 on the trap corpus); a calibrated defer threshold strictly dominating
always-answer under asymmetric costs while a fixed self-report threshold degrades under drift;
and a destination-aware escalation policy dominating always-answer on the held-out half of the
temporal split (expected utility 0.47 vs 0.20, unsafe-action rate 0.13 vs 0.27, escalation rate
0.33). Under injected overconfidence drift — measured like-for-like on the held-out half, raw
self-report against raw self-report — a stale self-report threshold suppresses escalation
exactly when it is most needed: human-intervention share 21% → 0% while the unsafe-action rate
rises 18.5% → 29%, whereas recalibrated historical scores hold the frontier exactly fixed
(outcomes are drift-invariant, so refitting on the drifted earlier half reproduces the same
calibration). These are fixture numbers validating the machinery, not evidence about real models.

A second research artifact implements the #932 leaf's own measurements:
`packages/maistro-rsi/tests/test_m8e3_heterogeneous_disagreement_research.py` (test suite only;
it loads the merged harness above by file path and imports nothing from `maistro`, so the
comparative ranking uses one metric implementation and no authority can accrete). It adds:

- a paired-panel data model: per-family answers judged against ground truth (verdicts and
  self-report are signals, never the judge), a declared primary family, and per-family
  correctness derived, never asked for;
- correlated-error accounting (the leaf's named risk): error overlap P(both wrong)/P(either
  wrong) across two families (1.0 = fully correlated, the point where a second family adds no
  independent evidence and the disagreement signal is blind by construction), joint error rate
  P(all families wrong), and a loud undefined result when neither family ever errs
  (independence unmeasured, not perfect);
- verifier confusion: false-approval rate (share of real errors waved through) and
  false-rejection rate (share of good answers killed), each undefined — an error, not a zero —
  when its outcome class is absent;
- a convex combination of success-oriented signals, so disagreement and verifier evidence can
  be scored jointly;
- incremental cost/latency accounting in call units: sequential self-consistency (#930) versus
  a concurrently-served family panel plus a sequential verifier pass (#932), with an
  incremental cost ratio against a stated baseline;
- a deterministic family-upgrade perturbation (a seeded fraction of one family's errors become
  correct) so overlap, joint error rate, and signal discrimination are re-measured after an
  upgrade instead of a threshold being silently carried across one.

On the deterministic paired fixture the leaf's comparative study runs end to end, scoring the
#930/#931 baselines with the same metrics: on the held-out split, verifier AUROC (≈ 0.86) >
cross-family agreement (≈ 0.74) > self-report (≈ 0.71), and the disagreement+verifier ensemble
reaches ≈ 0.92, strictly dominating both single signals; on the agreeing (correlated-error)
slice, family agreement is constant and blind — exactly the failure mode the hypothesis names —
while the verifier still separates its catches. These numbers are properties of the fixture's
construction (a 0.6 trap correlation, a 25 %-false-approval critic), demonstrated so the
machinery and the comparison are reproducible; they are NOT evidence about real model families.

## Benchmark procedure (what a real experiment must do)

1. Export judged decisions from the outcome seam: (context/task family, model family,
   self-reported confidence, observed outcome), plus repeated samples per task (#930) and
   paired heterogeneous-family answers / verifier verdicts (#932).
2. Split chronologically (`m8e_temporal_split`); fit historical calibration on the earlier
   split only (#931's leakage requirement).
3. On the held-out split, compare every signal against the raw self-report baseline and a
   no-confidence baseline: AUROC/AUPRC for error prediction, ECE/Brier for calibration,
   risk-coverage for selective answering.
4. For #932 specifically: measure the correlated-error overlap of every family pair
   (`m8e3_error_overlap`) and each verifier's false-approval/false-rejection rates
   (`m8e3_verifier_confusion`) before crediting any ensemble gain; a second family whose error
   set overlaps the first's buys nothing, however good the disagreement AUROC looks on the
   non-overlapping slice. Report the panel's incremental cost/latency against the
   self-consistency strategy (`m8e3_incremental_cost_ratio`), and re-run the whole comparison
   after any family upgrade (`m8e3_apply_family_upgrade`) — a signal threshold carried across
   an upgrade un-re-examined is reported as unsafe, not kept.
5. Sweep the defer threshold with the operator's stated costs (`EscalationCosts`); report the
   frontier against the always-answer baseline (#933), including unnecessary-deferral and
   unsafe-action rates, and the destination-aware frontier (human-intervention rate,
   escalation cost/latency, per-destination shares) over the operator's measured destination
   parameters.
6. Re-measure under injected overconfidence drift; a threshold that is not re-calibrated is
   reported as unsafe, not silently kept.
7. Emit per-leaf dispositions here. Cost accounting must include the extra samples, the
   second model family, the verifier, and the deferred decisions' latency — not only accuracy.

## Trust boundary

Experimental confidence scores are evidence, not authorization and not Goal truth. Nothing in
this change reads or writes a Goal, a Run authority, a routing decision, or a Warden/HITL/
delegation control; the policy frontiers return measurements only (frozen dataclasses of rates,
no actions). The destination-aware frontier's escalation destinations are *descriptions* of
where help could come from, with parameters measured elsewhere — the harness cannot invoke a
stronger model, a specialist Agent, a verifier, or a human, and simulates expected utility
under stated parameters without acting. Any future adoption must route through the earliest
owning milestone and the canonical authorization paths (ADR-068); a calibrated score may
*inform* the router or a HITL prompt, never substitute for one. #915's cascade thresholds are
likewise keep-confident research: its escalation criteria stay separated from routing authority
by design.

## Dispositions

- #930 (self-consistency / semantic entropy): **WATCH** — machinery ready; no real-model
  evidence yet. Move to INCUBATE on measured AUROC/AUPRC gain over self-report on
  representative MAIstro workloads with acceptable token cost/latency. The leaf now has
  its own comparison note and harness:
  [930 — self-consistency, semantic entropy, answer-variation signals](930-answer-variation-uncertainty-signals.md)
  (the three signal families side by side, with sampling temperature, the equivalence
  clusterer, and the confident-convergence blind spot identified as the variables a real
  experiment must control).
- #931 (historical outcome calibration): **WATCH** — the leaf's comparative study now exists
  and is fixture-validated (frequency / Beta-posterior / Platt / histogram / logistic
  estimators vs self-report and no-confidence baselines, leakage-safe temporal split,
  learning curves, drift and subgroup studies, maintenance-cost ledger;
  [`931-historical-outcome-calibration.md`](931-historical-outcome-calibration.md)). Still
  needs the real outcome-corpus run the leaf note records as its INCUBATE trigger.
- #932 (heterogeneous disagreement / verifiers): **WATCH** — the comparative machinery is now
  complete: correlated-error overlap, verifier confusion (false approval/rejection), convex
  signal combination, panel-vs-self-consistency cost/latency accounting, and an
  upgrade-robustness re-measurement run the leaf's full comparison (disagreement, verifier,
  #930/#931 baselines, and their ensemble) against observed outcomes on matched tasks.
  Correlated-error rates across real model families remain unmeasured until a paired real
  corpus exists; the fixture demonstrates the comparison's structure, not the hypothesis.
  Move to INCUBATE when, on a real paired corpus, the ensemble's AUROC/AUPRC gain over the
  #930/#931 baselines survives its incremental cost ratio, the measured error overlap is low
  enough that the second family contributes independent evidence, and the verifier's
  false-approval rate is tolerable for the slice it would gate. Adoption routes to
  model-routing owners.
- #933 (abstention / ask-for-help / escalation policies): **WATCH** — the destination-aware
  frontier (thresholds × stronger-model / specialist / verifier / HITL bands, reporting
  human-intervention rate, escalation cost/latency, unnecessary escalation, and drift
  robustness) is implemented and hand-checked on synthetic destination parameters only.
  Expected-utility improvement must be shown on real held-out tasks with measured destination
  outcomes (#915 cascade data), and any escalation destination remains inside canonical
  Warden/HITL/delegation authority.

The epic stays open until each leaf records a terminal disposition; WATCH is the honest
terminal state today. No adoption is authorized by this note.
