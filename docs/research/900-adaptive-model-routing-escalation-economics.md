# M8-B research epic — adaptive model routing, escalation, and inference economics

Epic: [#900](https://github.com/Agent-StrongHold/Project-mAIstro/issues/900).
Initiative: [#879](https://github.com/Agent-StrongHold/Project-mAIstro/issues/879).
Leaves: [#914](https://github.com/Agent-StrongHold/Project-mAIstro/issues/914) (M8-B1),
[#915](https://github.com/Agent-StrongHold/Project-mAIstro/issues/915) (M8-B2),
[#916](https://github.com/Agent-StrongHold/Project-mAIstro/issues/916) (M8-B3),
[#917](https://github.com/Agent-StrongHold/Project-mAIstro/issues/917) (M8-B4),
[#919](https://github.com/Agent-StrongHold/Project-mAIstro/issues/919) (M8-B5).
This note consolidates the family; each leaf's evidence and disposition lives in its own
note and remains authoritative for that leaf.

## Research question

Can MAIstro learn or infer which model/provider to use for each piece of work better than
the current static/configured routing approach, reducing cost and latency without
materially degrading task success?

## Candidate research → leaf mapping

| Epic candidate | Leaf | Note |
|---|---|---|
| task-conditioned/contextual routing | M8-B1 (#914) | [914-task-conditioned-model-routing.md](914-task-conditioned-model-routing.md) |
| cheap-model-first cascades and heterogeneous fallback | M8-B2 (#915) | [915-cheap-model-first-cascades.md](915-cheap-model-first-cascades.md) |
| confidence/uncertainty-triggered escalation | M8-B2 (#915) | same note; criterion interface defined against [#904](https://github.com/Agent-StrongHold/Project-mAIstro/issues/904) signal families |
| contextual-bandit or outcome-learned routing | M8-B3 (#916) | [916-contextual-bandit-model-routing.md](916-contextual-bandit-model-routing.md) |
| speculative parallel model calls and early stopping | M8-B4 (#917) | [917-speculative-parallel-model-calls.md](917-speculative-parallel-model-calls.md) |
| prompt/model co-routing | M8-B5 (#919) | [919-prompt-model-co-routing.md](919-prompt-model-co-routing.md) |
| per-Agent/per-capability specialization | M8-B5 (#919) | same note (hand-pinned `Binding.provider_name` vs evidence-derived pairs) |
| latency/cost/quality budget routing | M8-B1 (#914) | same note (`RouterBudget` expressiveness audit: exclusion-only levers) |

## Epic contract, operationalized

The epic requires experiments on real MAIstro routing/evaluation seams, comparison to a
fixed baseline, quality + cost + latency measurement, and that no experimental learner
becomes the production routing authority. How the family satisfied it:

- **Real seams.** Every harness selects through shipped selection code, not a
  re-implementation: B1/B4 route through
  [`CostAwareRouter`](../../packages/maistro-core/src/maistro/providers/router.py)
  (`select`/`fallback_chain`, ADR-038/ADR-079); B3's baseline is the real
  [`score_candidate`](../../packages/maistro-core/src/maistro/router/scorer.py) argmax
  over real `Intent`/`ModelConfig`/`RoutingConfig` objects; B5 treats the model axis
  (`CostAwareRouter`) and the prompt axis
  ([`InMemoryPromptManager`](../../packages/maistro-core/src/maistro/prompts/store.py))
  as the two orthogonal shipped seams they are. Cost/latency units everywhere are
  `ModelMetadata`'s ([`types.py`](../../packages/maistro-core/src/maistro/providers/types.py)).
- **Fixed baselines.** B1: the shipped router itself. B2: fixed strong-only baseline
  attached to every cascade run. B3: the shipped `score_candidate` argmax. B4:
  serial-fallback (the canonical cascade) plus single-strong. B5: a fixed (model,
  template) pair as the only judge.
- **Quality + cost + latency.** Every leaf reports all three axes plus the issue's
  extra measures (concentration, stability, leakage, regret, escalation rate,
  structured-output validity, maintenance burden — per leaf note).
- **No learner in authority.** The family changed no file under `packages/*/src`
  (verified across the five leaf commits). All artifacts are benchmark scripts under
  [`scripts/`](../../scripts/), test-suite-only harnesses under `tests/` /
  `packages/maistro-rsi/tests/`, recorded baselines under
  [`docs/benchmarks/`](../benchmarks/), and these research notes. Production adoption
  routes to the existing model-routing/evaluation owner per the epic exit; nothing here
  authorizes adoption.

## The seam facts the family established

Two structural facts, both test-pinned in-tree, frame every result below:

1. **The shipped model-selection seams are blind to the signal the research question is
   about.** `CostAwareRouter.select` never reads its `task` argument (pinned by
   `test_shipped_router_selection_ignores_the_task_descriptor` in
   [tests/test_bench_model_routing.py](../../tests/test_bench_model_routing.py));
   `score_candidate` is stateless across requests and consumes only operator catalog
   metadata plus live usage counters — no outcome label ever returns to the router.
2. **The only conditioning levers shipped today are exclusion and static pins.**
   `RouterBudget` can forbid models (cost/latency ceilings, `reasoning` flag) but cannot
   prefer one or protect a task whose context exceeds a model's window; the only
   evidence-derived per-workload pin mechanism is an operator's hand-pinned
   [`Binding.provider_name`](../../packages/maistro-core/src/maistro/capabilities/binding.py).

## Per-leaf records and dispositions

| Leaf | Artifact(s) | Headline measured result | Disposition |
|---|---|---|---|
| #914 task-conditioned routing | [bench_model_routing.py](../../scripts/bench_model_routing.py) · [baseline](../benchmarks/model-routing-baseline.json) · [tests](../../tests/test_bench_model_routing.py) | Shipped router sends 60k-token summarizations to a 4k-window model and reasoning-flagged plans to a non-reasoning model (38.4% success). A tier-conditioned candidate closes 84.5% of the achievable utility gap (success 93.5%, ~0.99¢/task, p95 1.3s); everything today's seam can express (budget-conditioned) captures ~36% and **collapses below the static baseline** (27% route failures) when the only reasoning-capable model circuit-breaks. | **INCUBATE** |
| #915 cheap-first cascades | [test_m8b2_cascade_benchmark_research.py](../../packages/maistro-rsi/tests/test_m8b2_cascade_benchmark_research.py) (37 checks) | No real paired (cheap, strong) outcome corpus exists, so the hypothesis is unevidenced on MAIstro workloads. The reproducible accounting machinery is built and validated: sunk cheap spend + escalation double-spend, false-confidence failures, dominance predicate, threshold sweep, #904-shaped signal interface with the leakage rule. Fixtures show a cascade can also *lose* money (always-escalate = baseline bill + every sunk attempt). | **WATCH** |
| #916 outcome-learned routing | [bench_outcome_routing.py](../../scripts/bench_outcome_routing.py) · [tests](../../tests/test_bench_outcome_routing.py) | In a synthetic drifting world with delayed (25-step), sparsified (20%) labels: the simplest learner — contextual means with two-level shrinkage toward the catalog prior plus exponential forgetting, greedy — cuts cumulative regret 4× vs the shipped `score_candidate` argmax (58 vs 231), recovers ~350 steps after a provider regression the static router never recovers from, posts the lowest exploration-attributable unsafe picks (3 vs 25–129), and dominates every bandit on stability. Caveat recorded: the bench's action space is unconstrained; production tier eligibility would leave half the world's traffic one arm. | **INCUBATE** |
| #917 speculative parallel calls | [bench_speculative_parallel.py](../../scripts/bench_speculative_parallel.py) · [baseline](../benchmarks/speculative-parallel-baseline.json) · [tests](../../tests/test_bench_speculative_parallel.py) | Early stopping's latency win is real but narrow (p95 −26% at unchanged p50/success/quality) and bought with a 4.7× token multiple, 82% of it cancellation waste; verifier selection buys quality (+0.16 score) at the worst latency and a 13.3% selection error; single-strong is dominated; provider diversity is load-bearing (same-provider fan-out: 0% outage survival). Every physical call mapped 1:1 to a governed Invocation — duplicates measured, never hidden. | **WATCH** |
| #919 prompt-model co-routing | [test_m8b5_corouting_benchmark_research.py](../../packages/maistro-rsi/tests/test_m8b5_corouting_benchmark_research.py) (30 checks) | No real paired (item × model × template) corpus exists; machinery is built and validated on the fixture grid the hypothesis is about. In-world: model-only routing ships structure failures (validity 1/3), prompt-only costs *more* than the fixed baseline, the bounded co-routing fit routes the interaction at 14.4× cheaper with validity 1.0 — with a 0.333 family generalization gap and 0.282 version-bump regret recorded, not hidden. | **WATCH** |

Reproducibility re-verified at head `af7996883`: the full five-leaf test set passes
(154 passed), the #914 recorded baseline's metric blocks regenerate exactly for both
availability scenarios (`all-available` and `opus-degraded`), and the #917 baseline JSON
regenerates byte-identically.

## Family-level findings

1. **Conditioning, not spending, is where the measured value is.** The only arms that
   beat their fixed baselines on the quality/cost frontier without multiples of extra
   spend are the conditioned ones (B1 tier-conditioned, B3 learned means). Arms that
   spend more to win (B4 fan-out, B2 escalation double-spend, B5 prompt-only) pay
   measurable multiples — 4.7–6.6× tokens or more-than-baseline bills — for tail
   latency or quality that conditioning reaches for approximately free.
2. **The simplest learner won, and the lesson generalizes within the family.** B3's
   dominant policy is contextual empirical means with shrinkage and forgetting — no
   deep bandit. B1's effective candidate is a static feature→tier map. What matters is
   the *feedback loop* (outcomes reaching selection) and the *safety shape*
   (shrinkage toward operator priors, hard capacity checks), not learner sophistication.
3. **Today's seam is not just suboptimal, it is fragile under conditioning.** B1's
   degraded scenario is the family's sharpest operational finding: expressing capability
   conditioning through `RouterBudget` alone inverts to worse-than-static under a single
   model circuit-break, because budget constraints fail closed per-candidate with no
   capacity-aware degradation. Any graduation must widen the seam (capacity/preference
   fields), not merely tune budgets.
4. **The family-wide blocker is telemetry, and it is the same for every leaf.** B2 and
   B5 could not run real experiments at all; B1 and B3 ran on simulators and say so
   loudly; B4's physics is authored. The missing input is identical everywhere:
   per-decision routing records (routing context, chosen model, recorded propensity,
   realized outcome/cost/latency) behind the governed
   [model chat seam](../../packages/maistro-core/src/maistro/capabilities/model_chat.py)
   with outcomes in the [outcome store](../../packages/maistro-core/src/maistro/memory/outcomes.py).
   B3's off-policy machinery is already written against exactly that schema; logging it
   is the single highest-leverage next step for the whole family and belongs to the
   routing/evaluation owner, not M8.
5. **Governed-path honesty held under the most invasive strategy.** B4's fan-out — the
   family's most invasive experiment — ran every candidate through Binding → Invocation
   → approved gateway provider, surfaced cancelled candidates as visible `UNKNOWN`
   Invocations, and failed its own audit rather than merging duplicates. The canonical
   execution model accommodated the research without modification.

## Trust boundary

This epic adds no authority and changes none. No production file under `packages/*/src`
was touched by any family commit; the harnesses are test-suite-only artifacts or
offline benchmark scripts; recorded baselines are frozen measurements, not actions. No
experimental policy reads a Goal, writes a Run, or makes a routing decision. Per the
epic contract and initiative guardrails, any production adoption (conditioned routing,
escalation criteria, outcome feedback, fan-out) is created by, and routed to, the
existing model-routing/evaluation owner through normal architecture and evidence gates.

## Exit

- Every leaf ends with exactly one terminal disposition: #914 **INCUBATE**, #915
  **WATCH**, #916 **INCUBATE**, #917 **WATCH**, #919 **WATCH**. Zero GRADUATE, zero
  REJECT.
- Family disposition: **INCUBATE** — the structural case for conditioning is verified
  in code and the in-world evidence is positive, but no leaf holds production evidence,
  because the per-decision routing telemetry a real replay needs does not exist.
  Re-evaluation triggers are recorded per leaf (real paired-corpus runs for #915/#919,
  replay with production eligibility for #916, measured tail-latency-bound workloads
  plus multi-provider egress for #917, recorded-Run replay through the B1 evaluator for
  #914).
- Production adoption is not implemented in M8; it routes to the existing
  model-routing/evaluation owner. The concrete handoff artifacts are the reusable B1
  evaluator, B3's OPE schema, and the B2/B5 harnesses' benchmark procedures.
