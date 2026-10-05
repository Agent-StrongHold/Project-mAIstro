# M8-B3 research note — contextual-bandit / outcome-learned model routing

Leaf: #916. Epic: #900. Offline prototype: `scripts/bench_model_routing.py`
(companion tests: `tests/test_bench_model_routing.py`). No product code is
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

`scripts/bench_model_routing.py` is a deterministic, fully offline bench (no
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

Reproduce: `uv run python scripts/bench_model_routing.py --output results.json`
(a manual-dispatch workflow, `.github/workflows/model-routing-bench.yml`,
re-runs it on demand and uploads the full results artifact).

## Record

Default configuration: 1500 steps, seeds 0–4, delay 25, label rate 0.8, drift
at step 700. Cumulative expected regret vs a clairvoyant oracle; "recovery"
is the first step whose trailing-100-decision post-drift regret averages
≤0.03; unsafe-exploration counts below-floor picks attributable to
learning-driven deviation from the static pick (the static baseline's own
unsafe picks are counted separately).

| policy | regret (±std) | pre-drift rate | post-drift rate | recovery | unsafe-expl. | quality | cost | on frontier |
|---|---|---|---|---|---|---|---|---|
| static-router | 231 ± 3 | 0.0049 | 0.2850 | never (0/5) | 0 | 0.635 | 3.60 | no |
| supervised-mean | 58 ± 12 | 0.0146 | 0.0598 | step ~1053 (5/5) | 21 ± 17 | 0.750 | 2.25 | yes |
| eps-greedy | 70 ± 9 | 0.0233 | 0.0673 | step ~1053 (5/5) | 37 ± 5 | 0.742 | 2.18 | yes |
| linucb | 105 ± 19 | 0.0679 | 0.0720 | step ~1143 (5/5) | 73 ± 27 | 0.719 | 1.79 | yes |
| thompson-linear | 153 ± 35 | 0.0890 | 0.1133 | step ~1199 (1/5) | 132 ± 51 | 0.687 | 1.66 | yes |

Against the issue's measures:

- **Offline regret**: the outcome-learned mean policy cuts cumulative regret
  4x vs the shipped router (58 vs 231) and its post-drift per-step regret rate
  by ~4.8x (0.060 vs 0.285). Pre-drift, the static router is better
  (0.0049 vs 0.0146) — learned policies pay a warm-up tax until labels arrive.
- **Adaptation after drift**: static-router never recovers within 800
  post-drift steps (it cannot — nothing feeds outcomes back). The learners
  recover ~350 steps after drift; with forgetting disabled (γ=1.0) adaptation
  degrades 2–3x (supervised-mean post-drift rate 0.059→0.186 on seed 1, and
  recovery fails outright on 2 of 3 seeds), so exponential forgetting is the
  load-bearing nonstationarity mechanism, not decoration.
- **Quality/cost frontier**: static-router is off-frontier (dominated on
  quality and cost); every learner is on it. The linear bandits buy lower
  average spend (1.66–1.79 vs 2.25) at a real quality cost.
- **Sample efficiency** (cumulative regret at observed-label checkpoints):
  supervised-mean 6.4 / 9.6 / 23.0 at 100/300/600 labels — ahead of eps-greedy
  (4.5 is lower at 100 only because its explore-start is shorter) and far
  ahead of linucb (22.6 / 45.5 / 76.8) and thompson (26.6 / 44.1 / 72.0).
  Shrinkage toward the catalog prior is what makes cold contexts usable.
- **Stability**: seed dispersion is small relative to means for the mean-based
  policies (58 ± 12); thompson is the least stable (153 ± 35, recovery in 1
  of 5 seeds).
- **Unsafe exploration risk**: the real cost of exploration is visible, not
  hypothetical. eps-greedy's perpetual ε alone causes ~37 below-floor picks
  per episode attributable to learning; thompson ~132. The plain greedy
  supervised mean keeps it at ~21 (mostly during its forced explore-start),
  and pure exploitation of the static router has zero by construction but
  697 total unsafe picks post-drift — safety-from-stupidity is not safety.
- **Propensity bias / OPE**: on the held-out log, clipped IPS tracks known
  truth for the deterministic static policy (|bias| 0.012) and doubly robust
  is tighter still (0.001), but both systematically *under*-estimate
  exploratory policies (linucb IPS bias 0.068, DR 0.075) — offline estimates
  of would-be explorers are pessimistic, so an offline gate on OPE numbers
  alone would under-admit exactly the policies that adapt fastest.
- **Delayed rewards / sparse labels**: with 25-step delayed delivery and 20%
  label loss the learners still adapt within ~350 post-drift steps; delay
  mostly costs early regret (labels arrive after the drift has already been
  paid for a while), sparsity mostly costs variance.

## Limits

Synthetic Bernoulli world with 8 context cells and 5 arms; binary success is
the only reward (no latency tail, no graded quality); drift is a single
sudden multiplicative shift rather than gradual or recurring; the logging
policy's propensities are recorded exactly, which real instrumentation must
guarantee but nothing yet enforces; reward draws go through one Bernoulli
channel while real outcome labels (task failure, user retry, escalation) have
their own bias; quota pressure is modeled at one request scale. All numbers
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
regret, sample efficiency, seed stability, and exploration-attributable unsafe
picks simultaneously; the bandits' only win is average spend. The concrete
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
