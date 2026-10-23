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

What this change does add is the reproducible metric machinery the leaves' benchmark procedure
requires, as a clearly separated research artifact:
`packages/maistro-rsi/tests/test_m8e_uncertainty_calibration_research.py` (test suite only; it
imports nothing from `maistro`, so it cannot become an authority by accident — M8 guardrails 1
and 2). Validated on deterministic, hand-checked synthetic fixtures, it implements:

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
  overconfidence-drift perturbation for threshold-robustness measurement.

The harness also demonstrates — on synthetic data only — the comparison the leaves must run on
real data: a disagreement-family signal outranking self-report as an error predictor
(AUROC 1.0 vs 0.0 on the trap corpus), and a calibrated defer threshold strictly dominating
always-answer under asymmetric costs while a fixed self-report threshold degrades under drift.

## Benchmark procedure (what a real experiment must do)

1. Export judged decisions from the outcome seam: (context/task family, model family,
   self-reported confidence, observed outcome), plus repeated samples per task (#930) and
   paired heterogeneous-family answers / verifier verdicts (#932).
2. Split chronologically (`m8e_temporal_split`); fit historical calibration on the earlier
   split only (#931's leakage requirement).
3. On the held-out split, compare every signal against the raw self-report baseline and a
   no-confidence baseline: AUROC/AUPRC for error prediction, ECE/Brier for calibration,
   risk-coverage for selective answering.
4. Sweep the defer threshold with the operator's stated costs (`EscalationCosts`); report the
   frontier against the always-answer baseline (#933), including unnecessary-deferral and
   unsafe-action rates.
5. Re-measure under injected overconfidence drift; a threshold that is not re-calibrated is
   reported as unsafe, not silently kept.
6. Emit per-leaf dispositions here. Cost accounting must include the extra samples, the
   second model family, the verifier, and the deferred decisions' latency — not only accuracy.

## Trust boundary

Experimental confidence scores are evidence, not authorization and not Goal truth. Nothing in
this change reads or writes a Goal, a Run authority, a routing decision, or a Warden/HITL/
delegation control; the policy frontier returns measurements only (frozen dataclasses of
rates, no actions). Any future adoption must route through the earliest owning milestone and
the canonical authorization paths (ADR-068); a calibrated score may *inform* the router or a
HITL prompt, never substitute for one. #915's cascade thresholds are likewise keep-confident
research: its escalation criteria stay separated from routing authority by design.

## Dispositions

- #930 (self-consistency / semantic entropy): **WATCH** — machinery ready; no real-model
  evidence yet. Move to INCUBATE on measured AUROC/AUPRC gain over self-report on
  representative MAIstro workloads with acceptable token cost/latency.
- #931 (historical outcome calibration): **WATCH** — Beta-smoothed estimator and leakage-safe
  split exist; needs the outcome corpus volume and drift-sensitivity study the leaf defines.
- #932 (heterogeneous disagreement / verifiers): **WATCH** — disagreement metric and ranking
  harness exist; correlated-error rates across model families are unmeasured until a paired
  corpus exists. Adoption routes to model-routing owners.
- #933 (abstention / ask-for-help / escalation policies): **WATCH** — frontier measured on
  synthetic costs only; expected-utility improvement must be shown on real held-out tasks, and
  any escalation destination remains inside canonical Warden/HITL/delegation authority.

The epic stays open until each leaf records a terminal disposition; WATCH is the honest
terminal state today. No adoption is authorized by this note.
