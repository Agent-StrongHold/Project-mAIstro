# M8-B1 research note — task-conditioned model routing vs the shipped static router

Leaf: #914. Epic: #900. Initiative: #879.

## Hypothesis

A router that conditions on task features (capability, tool use, context size,
code/reasoning class, latency budget) can lower cost/latency at equal success
rate versus the current static/configured routing.

## Canonical seam

Model selection goes through `CostAwareRouter.select(task, budget)`
(`packages/maistro-core/src/maistro/providers/router.py`, ADR-079) over an
`LLMProviderRegistry`; the governed call path is
`maistro.capabilities.model_chat.resolve_model_chat_provider`. Three verified
structural facts about the seam frame the whole question:

1. **The router ignores the task descriptor.** `select()` filters by budget,
   sorts candidates by `latency_p50_ms`, and walks fallback chains (ADR-038);
   the `task` argument is never read. Production callers pass a bare
   `RoutingTask(task_type="capability.model_chat")` and an unconstrained
   budget, so shipped routing is literally "fastest available model, always".
   Pinned by `test_shipped_router_selection_ignores_the_task_descriptor`.
2. **The only conditioning lever in the seam is exclusion.** `RouterBudget`
   carries `max_cost_cents`, `max_latency_ms`, and a `reasoning` flag — and no
   capacity, tier, or preference field. A budget can forbid models but cannot
   prefer one, and cannot protect a task whose context exceeds a model's
   window.
3. **Capability constraints do not soften via fallback.** With
   `reasoning=True`, `_satisfies` re-filters every fallback candidate, so when
   the only reasoning-capable model is circuit-broken, selection raises
   `NoEligibleModelError` — the route fails outright rather than degrading.

## Method

`scripts/bench_model_routing.py` is the offline/replay evaluator (results
recorded in `docs/benchmarks/model-routing-baseline.json`, runnable via the
manual `model-routing-bench.yml` workflow; deterministic, offline, blake2b
seeds — same seed, same numbers):

- **Corpus** — 2,400 tasks over six capability classes (chat, classification,
  extraction, summarization, code repair, planning) with observable features
  (class, context size, expected output size, tool use, reasoning requirement,
  latency SLO) and a HIDDEN per-task difficulty that only the outcome model
  sees. The descriptor type structurally cannot carry outcome data.
- **Outcome table** — one fixed deterministic simulator over (task, model)
  pairs, built once BEFORE any policy runs; every policy is scored against the
  identical table. Its shape is the escalation regularity the hypothesis rests
  on: cheap tiers succeed on easy work and fall off a cliff past a comfort
  zone; capable tiers degrade gently; reasoning-flagged tasks punish
  non-reasoning models; context beyond a model's `max_tokens` (registry
  metadata) is a hard failure. Cost comes from the shipped
  `compute_cost_cents`.
- **Policies** — `shipped-router` (the real `CostAwareRouter`, production call
  shape), `static-cheap` (a whole-corpus `RouterBudget` cost cap pushed to its
  zero-incremental-cost extreme), `budget-conditioned` (per-task `RouterBudget`
  from features, selection still via the real router), `tier-conditioned`
  (features → capacity floor + tier set, shipped latency preference inside; a
  candidate, NOT production code), and `oracle` (per-task utility argmax —
  "chosen after outcomes", the regret baseline).
- **Metrics** (per the issue) — success rate, cost (total/per-task/per-success),
  realized p50/p95 latency, deadline-miss rate, model and provider
  concentration (shares + HHI), routing stability (selection flip rate under
  ±5% feature jitter), feature leakage, and regret vs the oracle.

**Feature leakage** is audited two ways: structurally (the policy-visible
descriptor has no difficulty/outcome field — test-pinned) and empirically
(re-seeding ONLY the outcome realization must not move any outcome-blind
policy's decisions; the oracle is run through the same audit as the positive
control and does move, so the detector is not vacuous). Both scenarios report
zero violations.

**Honest scope limit:** the repository records no per-task routing telemetry,
so the replay corpus and outcomes are simulated. The experiment therefore
measures policy *structure* against a stated outcome model — it does not
measure production traffic. Every magnitude below is simulator-dependent; the
structural facts above are not. This is also why the disposition is not
GRADUATE.

## Record

All-available catalog (2,400 tasks; costs in cents):

| policy              | success | ¢/task | p50 ms | p95 ms | miss  | model HHI | utility | regret |
|---------------------|--------:|-------:|-------:|-------:|------:|----------:|--------:|-------:|
| shipped-router      | 0.384   | 0.0012 | 400    | 512    | 0.000 | 1.000     | 0.148   | 0.684  |
| static-cheap        | 0.497   | 0.0000 | 2500   | 3313   | 0.308 | 1.000     | −0.149  | 0.981  |
| budget-conditioned  | 0.622   | 0.4197 | 400    | 1078   | 0.000 | 0.604     | 0.398   | 0.434  |
| tier-conditioned    | 0.935   | 0.9937 | 676    | 1299   | 0.000 | 0.365     | 0.726   | 0.106  |
| oracle              | 0.998   | 0.5584 | 602    | 1475   | 0.000 | 0.320     | 0.832   | 0.000  |

- The shipped router's failures are structural, not price-related: it sends
  60k-token summarizations to a 4k-window model (hard capacity failure) and
  reasoning-flagged plans to a non-reasoning model. Its apparent cost advantage
  (0.0012 ¢/task) buys 38% success; cost-per-success comparisons flatter it
  only because failures are priced here as a bounded −0.25 utility, while real
  failed work re-queues, retries, or escalates to a human.
- Task conditioning via tiers closes **84.5% of the achievable utility gap**
  ((0.726 − 0.148) / (0.832 − 0.148)): success 38.4% → 93.5%, at ~0.99 ¢/task
  and p95 1.3s. The budget-conditioned variant — everything today's seam can
  express — captures roughly 36% of the gap, all of it from the one lever the
  seam has (reasoning escalation); it cannot protect large contexts because
  `RouterBudget` has no capacity field, and it cannot express "prefer capable"
  because budgets only exclude.
- Concentration moves exactly as conditioning predicts: model HHI 1.000 → 0.365
  (shipped routes 100% of tasks to one model); provider HHI 1.0 → 0.51. The
  oracle is MORE provider-concentrated (0.72, openai-heavy) than
  tier-conditioned — concentration is an output of the policy, not a target.
- Stability: the static router never flips (it is constant — perfectly stable
  and perfectly unresponsive); tier-conditioned flips on 1.1% of tasks under
  ±5% context jitter (tasks near the capacity/tier boundary). Conditioned
  routing buys adaptivity with a small, bounded instability.

Degraded catalog (`claude-3-opus` circuit-broken; the availability seam real
callers hit):

| policy              | success | route failures | miss  | utility |
|---------------------|--------:|---------------:|------:|--------:|
| shipped-router      | 0.384   | 0              | 0.000 | 0.148   |
| budget-conditioned  | 0.357   | 0.272          | 0.272 | 0.137   |
| tier-conditioned    | 0.826   | 0.038          | 0.037 | 0.607   |
| oracle              | 0.930   | 0              | 0.000 | 0.768   |

The degraded run is the sharpest finding: budget-conditioned routing **collapses
below the static baseline** — with the only reasoning-capable model gone, the
`reasoning=True` constraint fails hard (fact 3 above) and 27% of tasks get no
route at all — while the tier-conditioned candidate degrades gracefully to
82.6% success by letting the remaining powerful-tier model absorb the work
(the residual 3.8% route failures are tasks whose context exceeds that
model's 32k window — unrecoverable without a capacity-adequate model).
Capability conditioning expressed through today's seam is *more fragile* than
no conditioning at all.

## Threats to validity

- The outcome model is authored, not observed. Its escalation shape is the
  qualitative public record, but slopes, comfort zones, and the −0.25 miss
  penalty are modeling choices; a different author could shift magnitudes.
  What no plausible re-parameterization does is restore a 4k-window model's
  ability to summarize a 60k-token document — the capacity half of the gap is
  arithmetic, not calibration.
- The corpus's class mix and SLO bands are assumptions about MAIstro workload,
  not measurements of recorded Runs.
- Utility weights are reported but not load-bearing for the headline: raw
  success, cost, latency, and concentration are published alongside.
- The oracle assumes perfect per-task foreknowledge; it is a ceiling, not a
  proposal.

## Disposition

**INCUBATE.**

- The structural case is real and verified in code: the shipped seam ignores
  every task feature the hypothesis names, and its only conditioning lever
  (budget exclusion) is provably too weak — it captures ~36% of the achievable
  gap in the benign scenario and inverts to worse-than-static under a single
  model circuit-break.
- The evidence is not production evidence: outcomes are simulated. GRADUATE
  would require replaying recorded Runs — real model, tokens, latency, and
  outcome per task — through this same evaluator against the shipped router.
  The evaluator is now built and reusable; the missing input is telemetry:
  per-InvocationUsage model/output/cost already exists, per-task realized
  latency and outcome capture does not.
- Per the epic contract, production adoption routes to the existing
  model-routing/evaluation owner. This change ships no router change, no
  learner, no production code under `packages/*/src` — only the benchmark, its
  tests, the recorded baseline, and this note.
