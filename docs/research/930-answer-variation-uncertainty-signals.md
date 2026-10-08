# M8-E1 research note — self-consistency, semantic entropy, and answer-variation uncertainty signals

Leaf: #930. Epic: #904 (M8-E). Initiative: #879. Cross-referenced: #932 (M8-E3 —
heterogeneous-family disagreement, the correlated-error blind spot this leaf's
signals cannot see), #915 (M8-B2 — cascade escalation consumes these signals).

## Hypothesis

Variation across independent generations provides a useful uncertainty signal for
difficult MAIstro decisions, outperforming raw model self-reported confidence.

## Canonical seams

Any sampled signal originates in governed inference — Binding → Invocation → the
single approved gateway provider
(`packages/maistro-core/src/maistro/capabilities/model_chat.py`,
`packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`) — and
is judged against observed outcomes recorded in the canonical outcome store
(ADR-017, `packages/maistro-core/src/maistro/memory/outcomes.py`). The epic's
contract governs this leaf: experimental confidence scores are evidence, not
authorization and not Goal truth, and calibration is judged against observed
outcomes, never self-report. Cost/latency accounting follows the inference cost
conventions the #915 leaf recorded (`ModelMetadata` units). One adjacent seam is
deliberately not reused: the epic-level M8-E harness
(`packages/maistro-rsi/tests/test_m8e_uncertainty_calibration_research.py`)
covers all four M8-E leaves with one aggregate sample-agreement stand-in; this
leaf needs the three signal families the issue names *side by side*, so it ships
its own comparison module rather than overloading the epic harness.

## Record

This note does not report a provider experiment. No real-model corpus exists in
this repository's deterministic CI, and manufacturing one was out of scope;
absent evidence is recorded rather than simulated (M8 guardrail 3). This change
adds no product code, no feature flag, and touches no authority path.

What it adds is the leaf's reproducible comparison machinery as a separated
research artifact:
`packages/maistro-rsi/tests/test_m8e1_variation_uncertainty_research.py`
(test suite only; it imports nothing from `maistro`, and a test asserts that on
its own AST — M8 guardrails 1-2). It implements the issue's full measure list as
one comparison table over k sampled answers per judged decision:

- **self-consistency**: the modal answer's share of the k samples;
- **semantic entropy / clustering**: entropy over *semantic* clusters, with the
  clusterer behind a pluggable equivalence function (default: whitespace/case
  normalization). This is the embedding-free stand-in and the declared seam
  where a real entailment/embedding clusterer plugs in;
- **answer variation**: pairwise disagreement rate and distinct-answer ratio;
- **judging**: error-prediction AUROC/AUPRC (score = 1 − confidence, outcomes =
  observed failures), calibration error of the signal treated as P(success)
  (binwise ECE against observed outcomes — the epic's "judged against observed
  outcomes" sentence in code), Spearman correlation of predicted error with task
  difficulty, and token/latency accounting (k-fold sampling bills k ×
  tokens-per-sample; latency is ceil(k / parallelism) × per-call latency). Every
  comparison row carries the corpus's *recorded* per-sample token counts and
  latencies — absolute bill and latency bound, not just the sample multiple —
  so two corpora with identical k but different measured per-call costs are
  never indistinguishable.

What the deterministic fixtures demonstrate (synthetic arithmetic, **not**
evidence about real models; harness as committed in c3ea29752,
`uv run pytest …m8e1…` → 35 passed):

- **Temperature decides whether the k-fold bill buys anything.** On the same
  difficulty/outcome stream (identical seed, temperature only reshaping the
  sample distribution), the sampled signals' error AUROC degrades monotonically
  with sampling temperature — pairwise agreement 0.723 → 0.659 → 0.619 at
  temperature 0.6/1.0/1.6, while the unsampled self-report control stays fixed
  at 0.662. At temperature 0.6 every sampled signal outranks self-report; at
  1.6 every one falls below it. A real experiment must therefore report the
  sampling temperature next to any AUROC gain, or the comparison is not
  interpretable. The corpus applies temperature as a proper distribution
  transform — every category weight is exponentiated by 1/T and renormalized —
  and the limits are pinned by test: as T → ∞ every category (gold included)
  approaches a 0.25 share, and as T → 0 sampling collapses onto the modal
  category.
- **Semantic clustering is the best-calibrated of the issue's three families
  on both fixture families** (ECE 0.082 vs 0.082–0.194 on the stronger family;
  0.068 vs 0.079–0.129 on the weaker one) and surface-form synonyms are exactly
  where it beats vanilla self-consistency: on the hand-built synonym-noise
  fixture, surface self-consistency ties every decision at confidence 0.5 (error
  AUROC 0.5, chance) while equivalence-merged semantic clustering separates the
  classes fully (AUROC 1.0). The distinct-answer ratio that completes the
  variation family splits the calibration question: it is the best-calibrated
  signal on the stronger family (ECE 0.049) and the worst on the weaker one
  (0.159), a reminder that coarser variation metrics are not free simplifications.
- **All signals degrade on the harder family** (error AUROC ≈ 0.63–0.66 →
  ≈ 0.56–0.61 moving from the 0.8-skill to the 0.55-skill family): more scatter
  compresses the confidence range. Family sensitivity is measurable, which is
  the preconditions for the issue's model-family robustness measure.
- **Predicted error tracks task difficulty** (Spearman 0.42–0.62 across the
  sampled signals on the default corpus, weakest for the coarsest metric,
  distinct ratio) — the difficulty correlation the issue asks for is measurable
  end to end.
- **The blind spot is confirmed, not hidden**: when repeated sampling converges
  confidently on a *wrong* answer (the mirage tasks), agreement is maximal
  exactly where the model fails — on a mirage-vs-honest subset (60 confidently-wrong
  mirage decisions against 60 honest ones) the agreement signal's error AUROC is
  0.32, and with a 30% mirage share every signal's error AUROC drops below 0.5
  (0.33–0.40). k samples of one model detect *indecision*, not *confident
  convergence*; that residual risk is the heterogeneous-family/verifier question
  and belongs to M8-E3 (#932), not to more samples from the same model.
- **The equivalence function is load-bearing.** Semantic confidence on the same
  samples moves from 1.0 to 0.0 depending on whether the equivalence merges or
  splits two surface forms, and identical strings can never be split by any
  string→id map (the polysemy blind spot: three "bank" samples are one cluster
  with full confidence even when the model means different things). Real
  semantic entropy stands or falls with a meaning-aware clusterer; this harness
  records that as the open dependency, not as a solved detail.
- **Cost is part of the result**: k = 8 samples bill 8 × 48 = 384 tokens against
  a 48-token one-shot decision (8× multiple), 5600 ms sequential vs 700 ms fully
  parallel — every comparison row carries its sampling multiple *and* the
  corpus's recorded absolute token bill and latency bound, so an AUROC gain is
  never quoted without its bill and a cheap-samples corpus can never be confused
  with an expensive one at the same k.

## Benchmark procedure (what a real experiment must do)

1. Export a judged corpus from the outcome seam: representative MAIstro
   workload tasks with observed outcomes, the served model's single-sample
   self-report, and k independent re-samples per task (answer text, token
   counts, per-call latency) — collected through the governed seam at recorded
   sampling temperatures, for at least two model families.
2. Fix the equivalence clusterer (or embedding clusterer) per task family and
   record it with the results — the fixtures show it can move the signal from
   1.0 to 0.0, so an unreported equivalence is an uninterpretable result.
3. Score every signal family plus the self-report baseline with the module's
   comparison table: error AUROC/AUPRC, signal-as-probability ECE, difficulty
   correlation, per-decision token bill and latency bound.
4. Repeat per sampling temperature and per model family; report the temperature
   and family next to every AUROC point.
5. Partition tasks by error mode (indecision vs confident convergence, using
   mirage-like labeled subsets where available) and report the signals' AUROC
   per partition; route the confident-convergence residual to M8-E3's
   heterogeneous-family comparison instead of counting it as k-fold headroom.
6. Update the disposition here. The k-fold token bill and the deferred
   decisions' latency are part of the result, never a footnote.

## Trust boundary

Every number the harness produces is advisory evidence: it reads no Goal, writes
no Run authority, makes no routing decision, and touches no Warden/HITL/
delegation control. Records are frozen dataclasses of measurements; the module
imports nothing from `maistro` and asserts that on its own AST, so it cannot
become an authority by accident (M8 guardrails 1-2). Any future adoption routes
through the earliest owning milestone and the canonical authorization paths
(ADR-068): a variation signal may *inform* the router or a HITL prompt, never
substitute for one. The mirage finding additionally bounds the claim this leaf
may ever make: repeated sampling from one model must not be presented as
coverage for correlated, confidently-converged failures.

## Disposition

- #930 (self-consistency / semantic entropy / answer variation): **WATCH** —
  the comparison machinery is reproducible, its math is hand-validated, and the
  fixture study isolates the three variables a real experiment must control
  (sampling temperature, equivalence clusterer, error mode). But the issue's
  hypothesis is unevidenced on MAIstro workloads: no real-model corpus exists,
  and the fixtures show the ranking of the three signals *flips* with sampling
  temperature, so no synthetic result can stand in for the measurement. Move to
  **INCUBATE** when a real run on representative workloads shows a sampled
  signal beating self-report on error AUROC/AUPRC at its recorded temperature
  and equivalence, at an acceptable token/latency multiple, with the
  confident-convergence partition reported and routed. **REJECT** if real runs
  show the k-fold bill buying no discrimination outside indecision-mode errors
  that cheaper signals already catch.

No adoption is authorized by this note.
