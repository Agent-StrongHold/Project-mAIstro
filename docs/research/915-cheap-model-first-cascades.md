# M8-B2 research note — cheap-model-first cascades with confidence-triggered escalation

Leaf: #915. Epic: #900. Initiative: #879. Cross-referenced: #904 (M8-E — its signal
families are the escalation evidence this leaf consumes).

## Hypothesis

Starting with a cheaper/faster model and escalating only when confidence/evidence
thresholds fail can reduce inference spend materially without increasing task failure.

## Canonical seams

Routing authority is `CostAwareRouter`
(`packages/maistro-core/src/maistro/providers/router.py`): it filters by budget, prefers
the lowest-latency candidate, and walks ADR-038 fallback chains. A cheap-first cascade
with confidence-triggered escalation is a *policy change on this seam* — per the epic
exit, production adoption belongs to the routing owner, not to M8. Governed inference —
where both tiers' calls originate — runs Binding → Invocation → the single approved
gateway provider (`packages/maistro-core/src/maistro/capabilities/model_chat.py`,
`packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`). Cost/latency
units are `ModelMetadata`'s (cents per 1k input/output tokens, p50 milliseconds,
`packages/maistro-core/src/maistro/providers/types.py`).

Judging "without increasing task failure" needs outcome ground truth: the canonical
outcome seam is the outcome store (ADR-017,
`packages/maistro-core/src/maistro/memory/outcomes.py`). It records the *served* model
per outcome (`model_used`), so a paired (cheap, strong) corpus — the same item answered
by both tiers — requires a deliberate dual-run export; it cannot be reconstructed from
production traffic alone. Direct egress callers frozen in `quality/model-egress.json`
remain outside the governed seam; any cascade experiment must either cover those paths
or scope itself to the governed seam and record the rest as migration debt (the same
caveat the #935 note records). Human escalation authority (Warden/HITL, ADR-068) is a
different escalation and is untouched by this leaf.

## #904 signal availability at this head

The issue escalates "using deterministic escalation criteria from #904 research signals
where available". At this head (31d891a561) the #904 harness is **not merged** — it lives
on its research branch. This leaf therefore defines the criterion interface and
demonstrates it with: (1) the cheap tier's self-reported confidence; (2) named
per-task signals (the #904 disagreement/verifier family shape); and (3) a minimal,
clearly-attributed Beta-smoothed historical-calibration stand-in carrying the same
leakage rule (#904's estimator must be fitted on a prior period only). Absent signals
raise loudly — absent evidence is never fabricated into a score. When the #904 harness
lands, its estimators plug into the same interface without touching the accounting.

## Record

This note does not report a provider experiment. The deterministic CI environment holds
no provider credentials and no real paired (cheap, strong) outcome corpus exists
in-tree; manufacturing one was out of scope, and absent evidence is recorded rather than
simulated (M8 guardrail 3). This change adds no product code, no flag, and touches no
authority path.

What it adds is the reproducible measurement machinery the benchmark procedure needs, as
a separated research artifact:
`packages/maistro-rsi/tests/test_m8b2_cascade_benchmark_research.py` (test suite only; it
imports no maistro module, so it cannot become an authority by accident — M8 guardrails
1-2). Validated on deterministic hand-checked fixtures (37 checks), it implements:

- tier cost/latency accounting in `ModelMetadata` units, with the stated rules made
  explicit: an escalated item pays the completed cheap call (sunk cost) *plus* the strong
  call; latency is sequential; a provider-errored cheap call bills nothing but pays its
  attempt latency;
- the fixed strong-only baseline (the judge), attached to every cascade run for
  like-for-like comparison, plus cost reduction, quality delta, and a
  dominance predicate (equal-or-better quality at strictly lower cost);
- the issue's full measure list: total cost, mean/p95 latency, escalation rate,
  **false-confidence failures** (cheap answered below the quality bar because its claim
  cleared the threshold), unnecessary escalations (the cost-side twin), final success
  quality, and provider-error rate with both handling policies (escalate-on-error vs
  unhandled-error-as-failure);
- deterministic escalation criteria (strict threshold; scoring exactly at the threshold
  stays cheap), a threshold sweep, and stated-cost utility ranking with a deterministic
  tie-break — the sensitivity analysis the issue asks for.

What the fixtures demonstrate (synthetic arithmetic, **not** evidence about real models):

- On the arithmetic-proof corpus, a tuned threshold (0.85) catches an overconfident cheap
  failure and lands at 16.15¢ vs the 57.5¢ strong baseline at equal quality, while a low
  threshold (0.7) saves more money (1.15¢) but ships exactly that failure — quality 2/3.
  Always-escalate degenerates to the baseline bill plus every sunk cheap attempt
  (58.65¢): a cascade can lose money.
- On the 240-item two-regime fixture, a #904-shaped verifier signal that actually
  discriminates hard failures lets the cascade match baseline quality at 825.6¢ vs
  2280¢ (≈64% cost reduction, escalating 25% of items), while the self-report criterion
  on the same corpus either ships 14 false-confidence failures (threshold 0.9) or must
  escalate everything (2325.6¢) to stop shipping them — the escalation-evidence choice,
  not the threshold number, is what separates those frontiers.

Executed probe record (head 31d891a561, 2026-10-05):
`uv run pytest packages/maistro-rsi/tests/test_m8b2_cascade_benchmark_research.py -q` →
37 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module.

## Benchmark procedure (what a real experiment must do)

1. Export a paired corpus from the outcome seam: representative MAIstro workload items,
   each answered by both the cheap tier and the fixed strong tier, with observed
   outcomes, cheap-tier self-report, available #904 signals, token counts, and provider
   errors. Populate tier profiles from the provider registry (`ModelMetadata`).
2. Measure the fixed strong-only baseline over the identical item set.
3. Fit historical calibration (#904 rule) on a strictly earlier period only.
4. Run the cascade under each criterion — self-report, each available #904 signal,
   blends — sweeping the threshold; record cost, mean/p95 latency, escalation rate,
   false-confidence failures, unnecessary escalations, final success quality, and
   provider-error rate per point.
5. Report the dominance frontier and its threshold sensitivity under stated utility
   weights; report the always-escalate and never-escalate degenerate points as bounds.
6. Update the disposition here. Cost accounting must include the sunk cheap attempts and
   the escalated items' double spend, never the strong-tier bill alone.

## Trust boundary

Confidence research and routing authority stay separate — this leaf's own contract
sentence and the epic's. Every number the harness produces is advisory evidence: it
reads no Goal, writes no Run authority, makes no routing decision, and touches no
Warden/HITL/delegation control. A threshold that survives a real experiment reaches
production only as a change to the canonical routing seam owned by the routing owner
(epic exit), where it remains subject to the existing budget/fallback semantics — this
harness never becomes a second routing authority, and its outputs are frozen
measurements, not actions.

## Disposition

- #915 (cheap-model-first cascades, confidence-triggered escalation): **WATCH** — the
  measurement machinery is reproducible and its arithmetic is validated, but no real
  paired-corpus experiment exists, so the hypothesis is unevidenced on MAIstro
  workloads. Move to **INCUBATE** when a real run on representative workloads shows a
  material cost reduction at non-inferior final success quality with bounded
  false-confidence failures, and the routing owner has the result. **REJECT** if real
  runs show false-confidence failures dominating the savings under honest cost
  accounting (sunk cheap spend included). Provider-error sensitivity and threshold
  robustness must be reported either way.

No adoption is authorized by this note.
