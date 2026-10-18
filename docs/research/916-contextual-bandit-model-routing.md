# M8-B3 research note — contextual-bandit / outcome-learned model routing

Leaf: #916. Epic: #900. Offline prototype: `scripts/bench_outcome_routing.py`
(companion tests: `tests/test_bench_outcome_routing.py`). No product code is
changed by this note.

## Hypothesis

A routing policy learned from historical task outcomes can outperform the
manually tuned static weights as model/provider performance changes over time.

## Canonical seam

The shipped router is `score_candidate`
(`packages/maistro-core/src/maistro/router/scorer.py`): per request it scores a
candidate as `quality^(quality_weight·priority_mult)·(1+speed bonus) /
(1+normalized_cost)^cost_weight`, with scarcity from provider quota
(`router.scarcity`) and paygo ordering. It is stateless across requests and
consumes only operator catalog metadata (`ModelConfig.quality`, strengths,
speed) plus live usage counters. **No outcome label ever returns to the
router**: adaptation today happens only when an operator edits catalog
metadata. That absent feedback loop is exactly the gap this issue asks about;
the prototype does not add one to production.

## Prototype

`scripts/bench_outcome_routing.py` is a deterministic, fully offline bench (no
network, no database). A synthetic world defines ground-truth
per-(task, complexity, model) success probabilities for 5 arms across 3
providers; every policy selects through real `Intent`/`ModelConfig`/
`ProviderConfig`/`RoutingConfig` objects, and the baseline ("static-router")
is the real `score_candidate` argmax — not a re-implementation. Catalog
metadata is deliberately stale relative to true probabilities. At `--drift-at`
the world mutates (a provider degrades x0.55 pushing arms below the 0.5 safety
floor, a cheap model silently improves +0.08) while catalog metadata stays
frozen. Feedback reaches policies only through a delayed (25 steps ± jitter),
sparsified (20% dropped) binary channel — delayed rewards and sparse labels
are enforced by the channel, not assumed away. Provider quota drains with
usage through the production daily-budget formula. Off-policy evaluation
replays a 2000-row logged dataset from an eps-greedy (0.2) static-router
logger with recorded propensities, comparing clipped IPS and doubly-robust
estimates against each policy's known on-policy truth.

Policies: `static-router` (baseline), `supervised-mean` (contextual
per-cell empirical success with two-level Beta-Binomial shrinkage toward the
arm mean and the catalog prior, exponential forgetting γ=0.99, 15-step forced
explore-start, otherwise greedy), `eps-greedy` (ε=0.05 perpetual exploration),
`linucb` (disjoint, α=0.5, discounted), `thompson-linear` (linear-Gaussian
posterior sampling per arm).

Reproduce: `uv run python scripts/bench_outcome_routing.py --output results.json`
(a manual-dispatch workflow, `.github/workflows/outcome-routing-bench.yml`,
re-runs it on demand and uploads the full results artifact).

## Record

Default configuration: 1500 steps, seeds 0–4, delay 25, label rate 0.8, drift
at step 700. Cumulative expected regret vs a clairvoyant oracle; "recovery"
is the first step whose trailing-100-decision post-drift regret averages
≤0.03. Unsafe picks (true success < floor) are split three ways: picks the
static router would also have made (`static`), picks made by a policy's
exploration mechanism (`unsafe-expl.` — explore-start, ε-draw, optimism or
posterior sampling), and picks that merely deviated greedily from the static
pick (`unsafe-greedy` — exploitation of a wrong estimate, which the earlier
single-bucket accounting mislabelled as exploration).

| policy | regret (±std) | pre-drift rate | post-drift rate | recovery | unsafe-expl. | unsafe-greedy | quality | cost | on frontier |
|---|---|---|---|---|---|---|---|---|---|
| static-router | 231 ± 3 | 0.0049 | 0.2850 | never (0/5) | 0 | 0 | 0.635 | 3.60 | no |
| supervised-mean | 58 ± 14 | 0.0146 | 0.0598 | step ~1053 (5/5) | 3 ± 2 | 18 ± 18 | 0.750 | 2.25 | yes |
| eps-greedy | 70 ± 10 | 0.0233 | 0.0673 | step ~1053 (5/5) | 25 ± 5 | 12 ± 8 | 0.742 | 2.18 | yes |
| linucb | 102 ± 14 | 0.0701 | 0.0659 | step ~1155 (5/5) | 76 ± 28 | 0 | 0.721 | 1.74 | yes |
| thompson-linear | 151 ± 42 | 0.0857 | 0.1144 | never (0/5) | 129 ± 66 | 0 | 0.688 | 1.65 | yes |

(Dispersion is the sample standard deviation across the five seeds.)

Against the issue's measures:

- **Offline regret**: the outcome-learned mean policy cuts cumulative regret
  4x vs the shipped router (58 vs 231) and its post-drift per-step regret rate
  by ~4.8x (0.060 vs 0.285). Pre-drift, the static router is better
  (0.0049 vs 0.0146) — learned policies pay a warm-up tax until labels arrive.
- **Adaptation after drift**: static-router never recovers within 800
  post-drift steps (it cannot — nothing feeds outcomes back). The mean-based
  learners recover ~350 steps after drift and linucb ~455; thompson fails to
  recover on any seed. With forgetting disabled (γ=1.0) adaptation degrades
  2–3x (supervised-mean post-drift rate 0.059→0.186 on seed 1, and recovery
  fails outright on 2 of 3 seeds), so exponential forgetting is the
  load-bearing nonstationarity mechanism, not decoration.
- **Quality/cost frontier**: static-router is off-frontier (dominated on
  quality and cost); every learner is on it. The linear bandits buy lower
  average spend (1.65–1.74 vs 2.25) at a real quality cost.
- **Sample efficiency** (mean cumulative regret at observed-label checkpoints
  across all five seeds): at 100 labels eps-greedy leads (4.1 vs
  supervised-mean 5.4 — its explore-start is only one round), but from 300
  labels on the shrinkage toward the catalog prior is what makes cold
  contexts usable: supervised-mean 7.7 / 28.9 at 300/600, ahead of eps-greedy
  (9.3 / 35.1) and far ahead of linucb (40.8 / 63.0) and thompson
  (45.3 / 79.7).
- **Stability**: seed dispersion is small relative to means for the mean-based
  policies (58 ± 14); thompson is the least stable (151 ± 42, and it never
  meets the recovery bar on any seed).
- **Unsafe exploration vs unsafe exploitation**: the real cost of exploration
  is visible, not hypothetical — and it is now split honestly. eps-greedy's
  perpetual ε alone causes ~25 below-floor picks per episode through its
  exploration branch and another ~12 through greedy deviations; thompson's
  posterior sampling ~129. The supervised mean's exploration branch (its
  15-step forced explore-start) causes only ~3 — but it posts ~18 unsafe
  picks by greedily exploiting wrong estimates, a bucket the previous
  accounting mislabelled as exploration. Pure exploitation of the static
  router has zero exploration-attributable picks by construction yet 697
  total unsafe picks post-drift — safety-from-stupidity is not safety.
- **Propensity bias / OPE**: on the held-out log, with the truth measured on
  the exact actions each policy took (common random numbers, so policy
  stochasticity cannot leak into the bias), clipped IPS tracks the known
  truth for the deterministic static policy (|bias| 0.012) and doubly robust
  is tighter still (0.001); thompson's IPS is near-unbiased (0.001) once that
  leakage is removed. The residual pessimism concentrates where support or
  the direct model is weakest: both estimators still under-estimate
  eps-greedy (IPS 0.032, DR 0.042) and linucb (IPS 0.068, DR 0.075) —
  offline estimates of would-be explorers remain pessimistic, so an offline
  gate on OPE numbers alone would under-admit exactly the policies that
  adapt fastest.
- **Delayed rewards / sparse labels**: with 25-step delayed delivery and 20%
  label loss the mean-based learners still adapt within ~350 post-drift
  steps (linucb ~455); delay mostly costs early regret (labels arrive after
  the drift has already been paid for a while), sparsity mostly costs
  variance.

## Limits

Synthetic Bernoulli world with 8 context cells and 5 arms; binary success is
the only reward (no latency tail, no graded quality); drift is a single
sudden multiplicative shift rather than gradual or recurring; the logging
policy's propensities are recorded exactly, which real instrumentation must
guarantee but nothing yet enforces; reward draws go through one Bernoulli
channel while real outcome labels (task failure, user retry, escalation) have
their own bias; quota pressure is modeled at one request scale. **The action
space is unconstrained**: production classification raises `min_tier` to
`large` for complex requests (`classifier.engine`), after which
`router.filter._tier_in_range` would drop every small/medium arm — half this
world's traffic would have one eligible arm in production — while the bench's
`Ctx.to_intent()` leaves the tier band open so all five arms compete on every
context. Regret, frontier, and cost conclusions therefore describe an
unattainable-in-production action space; replaying with the production
eligibility filter applied is step zero of any incubation. All numbers
are in-world; none transfer without replay on real logged outcomes, which do
not exist today because outcomes are not logged against routing decisions.
No online exploratory routing was run or proposed (per the issue's
constraint).

## Disposition

Disposition: INCUBATE.

The hypothesis is confirmed in-world with a large, stable margin, and — the
operationally useful surprise — the winning policy is the simplest one:
contextual outcome means with two-level shrinkage toward the catalog prior
plus exponential forgetting, selected greedily. It dominates the bandits on
regret and seed stability, posts the lowest exploration-attributable unsafe
picks by an order of magnitude (3 vs 25–129), and is the most sample-efficient
learner from 300 labels on; the bandits' only wins are average spend and the
first 100 labels. Its ~18 unsafe picks from greedy exploitation of wrong
estimates are the honest price of that dominance — visible now that the
accounting separates them from exploration. The concrete
incubation path, in order: (1) log per-decision routing context, chosen model,
recorded propensity, and eventual task outcome behind the existing request
path — the OPE machinery here is already written against exactly that schema;
(2) replay offline with doubly-robust estimates plus conservative bounds,
knowing exploratory policies will read pessimistic; (3) only consider a
shadow (no user impact) deployment of the greedy mean-with-forgetting policy
after it wins on real replay data. Do not graduate on the strength of this
synthetic evidence alone; do not reject — the failure mode it fixes (static
weights silently rotting 4.8x past a provider regression) is measured, not
imagined.
