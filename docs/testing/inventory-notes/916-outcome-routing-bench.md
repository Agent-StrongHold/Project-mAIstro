---
inventory-delta:
  tests/: +31
---
# 916 offline model-routing research bench

Implements the #916 (RESEARCH M8-B3) deliverable: an offline, deterministic
prototype comparing outcome-learned routing policies (contextual means with
catalog-prior shrinkage + forgetting, eps-greedy, LinUCB, contextual
Thompson) against the real production static scorer
(`maistro.router.scorer.score_candidate`) under delayed, sparsified,
nonstationary feedback, plus off-policy (clipped IPS / doubly robust)
evaluation on a propensity-logged dataset. The research record and the
GRADUATE/INCUBATE/REJECT/WATCH disposition are in
`docs/research/916-contextual-bandit-model-routing.md`. No product code
changes.

All additions, no removals:

- `scripts/bench_outcome_routing.py` — the bench itself (measured root:
  `scripts/` is covered by the quality.yml producer, and this file sits at
  99% line / 98% branch under `tests/test_bench_outcome_routing.py`).
- `tests/test_bench_outcome_routing.py` — **+31 tests** in the root `tests/`
  suite: the static baseline provably routes through production
  `score_candidate` including its no-paygo filter path; world drift mutates
  ground truth while catalog metadata stays stale; the feedback channel
  never delivers dropped labels or early ones; explore-start/epsilon/greedy
  policy contracts; LinUCB/Thompson learn a rewarded arm only once all arms
  hold evidence (unobserved arms keep their optimism bonus by design) and
  optimism still abandons a mediocre observed arm; the discounted linear
  posteriors keep their ridge at full strength (no singular covariance after
  thousands of labels on one arm); `RecoveryTracker` fires once at threshold
  on a sliding window; episode determinism; the unsafe-pick three-way
  decomposition (`static + exploration + greedy deviation == total`) with
  each bucket pinned to the branch that actually made the pick; the learner
  halves static-router cumulative regret across fixed seeds after drift;
  OPE estimators track known truth (truth taken from the exact evaluated
  trajectory, even for stochastic policies), track clipping, and the CLI
  rejects configurations that would fake a post-drift phase or run zero
  seeds; sample-efficiency checkpoints average every requested seed;
  frontier dominance/tie logic; and `main()`'s published JSON payload shape.

The bench is deterministic (seeded RNGs, no wall-clock assertions), so every
property above is pinned exactly, and runs offline at small scale to respect
the root suite's `--timeout=30` producer budget.
