#!/usr/bin/env python3
"""Offline model-routing research bench (issue #916, RESEARCH M8-B3).

Answers, with numbers instead of guesses, whether a routing policy learned
from historical task outcomes can beat the shipped static scorer as model
quality drifts. Everything is deterministic and offline: the world (ground
per-(context, model) success probabilities) is generated, feedback is
delivered through a delayed, sparsified, propensity-logged channel, and the
"current router" baseline is the *real* production scorer
(``maistro.router.scorer.score_candidate``) driven with real
Intent/ModelConfig/ProviderConfig/RoutingConfig objects — not a re-implementation
of it. No network, no PostgreSQL, no product code changes: this bench exists
to produce the GRADUATE/INCUBATE/REJECT/WATCH disposition, not to ship a
learner.

What it addresses from the issue, mechanically:

* delayed rewards       — outcomes are queued and delivered ``--delay`` steps
                          later (plus jitter); policies only ever ``observe``
                          what the channel delivers;
* sparse labels         — each outcome is dropped independently with
                          probability ``1 --label-rate`` and never delivered;
* nonstationary models  — at ``--drift-at`` the ground-truth table mutates
                          (a provider degrades below the safety floor, a cheap
                          model improves) while catalog metadata stays stale;
* exploration risk      — "unsafe" picks (true success < SAFETY_FLOOR) are
                          decomposed into picks the static router would also
                          have made, picks made by a policy's exploration
                          mechanism (explore-start, ε-draw, optimism bonus,
                          posterior sampling), and picks that merely deviated
                          greedily from the static router — a greedy exploit
                          of a wrong estimate is exploitation risk, not
                          exploration risk, and the two must not share a
                          bucket;
* propensity bias       — a held-out logged dataset from an eps-greedy
                          static-router logger carries recorded propensities;
                          IPS and doubly-robust off-policy estimates are
                          compared against the policies' known on-policy
                          truth to expose estimator bias.

Measured: offline regret (cumulative, per phase, vs a clairvoyant oracle),
quality/cost frontier, adaptation speed after simulated drift, stability
(across seeds), sample efficiency (regret at observed-label checkpoints), and
unsafe exploration risk.

Usage:
    uv run python scripts/bench_model_routing.py [--steps 1500] [--seeds 5]
        [--delay 25] [--label-rate 0.8] [--drift-at 700] [--output results.json]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "maistro-core" / "src"))

from maistro.router.scorer import score_candidate
from maistro.types.config import RoutingConfig
from maistro.types.intent import Intent
from maistro.types.model import ModelConfig, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# ─── World definition ────────────────────────────────────────────────────────
#
# Five arms across three providers. Catalog metadata (what the static scorer
# sees) is deliberately STALE relative to true success probabilities — that is
# the issue's hypothesis: manual weights lag reality, learned policies need not.

TASK_TYPES: tuple[str, ...] = ("chat", "code", "extract", "summarize")
COMPLEXITIES: tuple[str, ...] = ("simple", "complex")

ARM_NAMES: tuple[str, ...] = (
    "alpha-max",  # expensive flagship; provider alpha degrades at drift
    "alpha-mini",  # small alpha model; degrades with its provider
    "beta-pro",  # mid-price workhorse; unaffected by the drift
    "beta-nano",  # cheapest; silently improves at drift
    "gamma-flash",  # under-rated by catalog pre-drift; collapses at drift
)
N_ARMS = len(ARM_NAMES)

# Success probability, PRE drift: arm index → per task/complexity table.
PRE_DRIFT: dict[int, dict[str, dict[str, float]]] = {
    0: {
        "chat": {"simple": 0.80, "complex": 0.85},
        "code": {"simple": 0.88, "complex": 0.92},
        "extract": {"simple": 0.75, "complex": 0.80},
        "summarize": {"simple": 0.82, "complex": 0.86},
    },
    1: {
        "chat": {"simple": 0.68, "complex": 0.60},
        "code": {"simple": 0.40, "complex": 0.30},
        "extract": {"simple": 0.50, "complex": 0.42},
        "summarize": {"simple": 0.60, "complex": 0.52},
    },
    2: {
        "chat": {"simple": 0.82, "complex": 0.78},
        "code": {"simple": 0.70, "complex": 0.62},
        "extract": {"simple": 0.72, "complex": 0.66},
        "summarize": {"simple": 0.84, "complex": 0.80},
    },
    3: {
        "chat": {"simple": 0.50, "complex": 0.42},
        "code": {"simple": 0.30, "complex": 0.22},
        "extract": {"simple": 0.66, "complex": 0.58},
        "summarize": {"simple": 0.55, "complex": 0.46},
    },
    4: {
        "chat": {"simple": 0.72, "complex": 0.66},
        "code": {"simple": 0.74, "complex": 0.70},
        "extract": {"simple": 0.60, "complex": 0.54},
        "summarize": {"simple": 0.70, "complex": 0.64},
    },
}

# Post-drift ground truth: the two alpha models degrade x0.55 (provider-side
# regression — every arm on the provider drops below or near the safety floor),
# gamma-flash collapses x0.55 (silent quality regression), beta-nano improves
# +0.08 (silent upgrade). Catalog metadata does not change.
_POST_DRIFT_MUTATION: dict[int, Callable[[float], float]] = {
    0: lambda p: round(p * 0.55, 3),
    1: lambda p: round(p * 0.55, 3),
    2: lambda p: p,
    3: lambda p: round(min(0.95, p + 0.08), 3),
    4: lambda p: round(p * 0.55, 3),
}

POST_DRIFT: dict[int, dict[str, dict[str, float]]] = {
    arm: {
        task: {cx: _POST_DRIFT_MUTATION[arm](PRE_DRIFT[arm][task][cx]) for cx in COMPLEXITIES}
        for task in TASK_TYPES
    }
    for arm in range(N_ARMS)
}

SAFETY_FLOOR = 0.5  # true success below this = unsafe pick for that context
REQUEST_TOKENS = 1200
QUOTA_DAY_STEPS = 200  # per-provider usage counters reset every N steps

# Stale operator catalog — exactly what the production scorer is given.
CATALOG: dict[int, tuple[ModelConfig, ProviderConfig]] = {
    0: (
        ModelConfig(
            provider="alpha",
            litellm_id="alpha/alpha-max",
            tier="large",
            quality=0.90,
            speed=40,
            strengths=("code", "reasoning"),
        ),
        ProviderConfig(
            free_tokens=30_000_000, overage_cost_per_1k_input=6.0, overage_cost_per_1k_output=6.0
        ),
    ),
    1: (
        ModelConfig(
            provider="alpha",
            litellm_id="alpha/alpha-mini",
            tier="small",
            quality=0.60,
            speed=95,
            strengths=("chat",),
        ),
        ProviderConfig(
            free_tokens=30_000_000, overage_cost_per_1k_input=6.0, overage_cost_per_1k_output=6.0
        ),
    ),
    2: (
        ModelConfig(
            provider="beta",
            litellm_id="beta/beta-pro",
            tier="medium",
            quality=0.72,
            speed=70,
            strengths=("chat", "summarize"),
        ),
        ProviderConfig(
            free_tokens=15_000_000, overage_cost_per_1k_input=2.0, overage_cost_per_1k_output=2.0
        ),
    ),
    3: (
        ModelConfig(
            provider="beta",
            litellm_id="beta/beta-nano",
            tier="small",
            quality=0.50,
            speed=120,
            strengths=("extract",),
        ),
        ProviderConfig(
            free_tokens=15_000_000, overage_cost_per_1k_input=2.0, overage_cost_per_1k_output=2.0
        ),
    ),
    4: (
        ModelConfig(
            provider="gamma",
            litellm_id="gamma/gamma-flash",
            tier="medium",
            quality=0.55,
            speed=110,
            strengths=("chat", "code"),
        ),
        ProviderConfig(
            free_tokens=6_000_000, overage_cost_per_1k_input=0.8, overage_cost_per_1k_output=0.8
        ),
    ),
}

# List price (USD per 1k tokens blended) — the frontier's cost axis.
LIST_COST_PER_1K: tuple[float, ...] = (3.00, 0.15, 0.80, 0.05, 0.35)

TASK_STRENGTHS: dict[str, tuple[str, ...]] = {
    "chat": ("chat",),
    "code": ("code",),
    "extract": ("extract",),
    "summarize": ("summarize",),
}

ROUTING_CFG = RoutingConfig()  # shipped defaults: quality_weight .6, cost_weight .4


def true_success_prob(arm: int, ctx: Ctx_like, phase: int) -> float:
    """Ground-truth success probability (hidden from every policy)."""
    table = PRE_DRIFT if phase == 0 else POST_DRIFT
    return table[arm][ctx.task][ctx.complexity]


@dataclass(frozen=True)
class Ctx:
    """One routed request's context."""

    task: str
    complexity: str

    def key(self) -> tuple[str, str]:
        return (self.task, self.complexity)

    def to_intent(self) -> Intent:
        return Intent(
            task_type=self.task,
            complexity="complex" if self.complexity == "complex" else "simple",
            tier="P2",
            preferred_strengths=TASK_STRENGTHS[self.task],
        )


Ctx_like = Ctx


def sample_context(rng: random.Random) -> Ctx:
    """Context distribution: task types and complexities drawn uniformly."""
    return Ctx(task=rng.choice(TASK_TYPES), complexity=rng.choice(COMPLEXITIES))


def static_router_pick(ctx: Ctx, usage_pcts: dict[str, float]) -> int:
    """The current router: real score_candidate, argmax over the catalog.

    Returns the chosen arm, or arm 0 if every candidate is filtered (in this
    world that only happens on full quota exhaustion without paygo, which the
    catalog's paygo providers preclude; the branch keeps the function total).
    """
    intent = ctx.to_intent()
    best_arm, best_score = 0, -math.inf
    for arm in range(N_ARMS):
        model_cfg, provider_cfg = CATALOG[arm]
        cand = score_candidate(
            f"arm{arm}",
            model_cfg,
            provider_cfg,
            intent,
            ROUTING_CFG,
            usage_pcts.get(model_cfg.provider, 0.0),
        )
        if cand is not None and cand.score > best_score:
            best_arm, best_score = arm, cand.score
    return best_arm


# ─── Delayed, sparse feedback channel ────────────────────────────────────────


class FeedbackChannel:
    """Queues outcomes and delivers them delay+jitter steps after selection.

    ``deliver_due`` must be called before each selection; it invokes
    ``policy.observe`` only for outcomes the channel actually carries (sparse
    labels are dropped at enqueue time, never delivered late as None).
    """

    def __init__(
        self,
        delay: int,
        max_jitter: int,
        label_rate: float,
        rng: random.Random,
        on_observe: Callable[[Ctx, int, float], None],
    ) -> None:
        self._delay = delay
        self._max_jitter = max_jitter
        self._label_rate = label_rate
        self._rng = rng
        self._on_observe = on_observe
        self._pending: list[tuple[int, Ctx, int, float]] = []
        self.delivered = 0
        self.enqueued = 0
        self.dropped = 0

    def enqueue(self, step: int, ctx: Ctx, arm: int, success: bool) -> None:
        if self._rng.random() >= self._label_rate:
            self.dropped += 1
            return
        arrive = step + self._delay + self._rng.randint(0, self._max_jitter)
        self._pending.append((arrive, ctx, arm, 1.0 if success else 0.0))
        self.enqueued += 1

    def deliver_due(self, step: int) -> None:
        still: list[tuple[int, Ctx, int, float]] = []
        for item in self._pending:
            if item[0] <= step:
                _, ctx, arm, reward = item
                self._on_observe(ctx, arm, reward)
                self.delivered += 1
            else:
                still.append(item)
        self._pending = still


# ─── Policies ────────────────────────────────────────────────────────────────


class Policy:
    """A routing policy. select() must be deterministic given internal state
    plus (for exploration) its own rng; observe() is invoked only for
    delivered feedback.

    select() must leave ``last_choice_exploratory`` recording whether THIS
    choice came from the policy's exploration mechanism (forced explore-start,
    ε-draw, optimism bonus, posterior sampling) rather than a greedy or
    exploitative decision — the unsafe-risk accounting splits on exactly this
    flag, so mislabelling a greedy pick as exploration would launder
    exploitation mistakes into the exploration-risk metric.
    """

    name: str = "policy"

    def __init__(self, seed: int) -> None:
        # Seeded so every episode is reproducible run-to-run; the seedable,
        # non-cryptographic PRNG *is* the design here, and nothing in the
        # offline bench touches a secret or a security boundary.
        self._rng = random.Random(seed)  # DevSkim: ignore DS148264 until 2027-12-31
        self.last_choice_exploratory = False

    def select(self, ctx: Ctx, usage_pcts: dict[str, float], step: int) -> int:
        raise NotImplementedError

    def observe(self, ctx: Ctx, arm: int, reward: float) -> None:
        raise NotImplementedError

    def observed_labels(self) -> int:
        return 0


class StaticRouterPolicy(Policy):
    """Baseline: the shipped static scorer. Learns nothing, explores nothing."""

    name = "static-router"

    def select(self, ctx: Ctx, usage_pcts: dict[str, float], step: int) -> int:
        return static_router_pick(ctx, usage_pcts)

    def observe(self, ctx: Ctx, arm: int, reward: float) -> None:
        pass


class CatalogPriorMeanPolicy(Policy):
    """Contextual outcome-learned means with two-level Beta-Binomial shrinkage:

    per-(context cell, arm) counts shrink toward the arm's global posterior
    mean, which shrinks toward the operator catalog's (stale) quality
    estimate. Sparse labels therefore still move a mean, and cold context
    cells fall back to arm-level evidence instead of a blind prior. Pure
    greedy selection; exploration comes only from the explore-start
    round-robins.
    """

    name = "supervised-mean"
    prior_weight = 8.0  # pseudo-observations backing the catalog prior
    cell_weight = 4.0  # pseudo-observations backing the arm-level prior
    gamma = 0.99  # exponential forgetting: nonstationary models, no cliff

    def __init__(self, seed: int, explore_start_rounds: int = 3, epsilon: float = 0.0) -> None:
        super().__init__(seed)
        self._explore_start = explore_start_rounds * N_ARMS
        self._epsilon = epsilon
        self._alpha = [0.0] * N_ARMS
        self._beta = [0.0] * N_ARMS
        self._cell_alpha: dict[tuple[tuple[str, str], int], float] = {}
        self._cell_beta: dict[tuple[tuple[str, str], int], float] = {}
        self._labels = 0
        self._forced = 0

    def _arm_mean(self, arm: int) -> float:
        catalog_q = CATALOG[arm][0].quality
        return (self._alpha[arm] + self.prior_weight * catalog_q) / (
            self._alpha[arm] + self._beta[arm] + self.prior_weight
        )

    def _mean(self, cell: tuple[str, str], arm: int) -> float:
        key = (cell, arm)
        ca = self._cell_alpha.get(key, 0.0)
        cb = self._cell_beta.get(key, 0.0)
        return (ca + self.cell_weight * self._arm_mean(arm)) / (ca + cb + self.cell_weight)

    def select(self, ctx: Ctx, usage_pcts: dict[str, float], step: int) -> int:
        if step < self._explore_start and self._forced < self._explore_start:
            arm = self._forced % N_ARMS
            self._forced += 1
            self.last_choice_exploratory = True
            return arm
        if self._epsilon > 0.0 and self._rng.random() < self._epsilon:
            self.last_choice_exploratory = True
            return self._rng.randrange(N_ARMS)
        best_arm, best_mean = 0, -math.inf
        for arm in range(N_ARMS):
            m = self._mean(ctx.key(), arm)
            if m > best_mean:
                best_arm, best_mean = arm, m
        self.last_choice_exploratory = False
        return best_arm

    def observe(self, ctx: Ctx, arm: int, reward: float) -> None:
        # Discounted counts: pre-drift evidence fades instead of anchoring the
        # posterior while the world has moved (the nonstationarity answer;
        # without it, adaptation after drift is measured ~2x slower).
        g = self.gamma
        self._alpha = [g * a for a in self._alpha]
        self._beta = [g * b for b in self._beta]
        self._cell_alpha = {k: g * v for k, v in self._cell_alpha.items()}
        self._cell_beta = {k: g * v for k, v in self._cell_beta.items()}
        self._alpha[arm] += reward
        self._beta[arm] += 1.0 - reward
        key = (ctx.key(), arm)
        self._cell_alpha[key] = self._cell_alpha.get(key, 0.0) + reward
        self._cell_beta[key] = self._cell_beta.get(key, 0.0) + (1.0 - reward)
        self._labels += 1

    def observed_labels(self) -> int:
        return self._labels


class EpsilonGreedyPolicy(CatalogPriorMeanPolicy):
    """Catalog-prior empirical means + perpetual uniform exploration."""

    name = "eps-greedy"

    def __init__(self, seed: int, epsilon: float = 0.05) -> None:
        super().__init__(seed, explore_start_rounds=1, epsilon=epsilon)


# ─── Linear-algebra helpers (pure stdlib — no numpy in the runtime) ─────────


def mat_inverse(a: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inverse with partial pivoting. Raises on singular input."""
    n = len(a)
    m = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ZeroDivisionError("singular matrix in LinUCB/TS posterior")
        m[col], m[piv] = m[piv], m[col]
        diag = m[col][col]
        m[col] = [v / diag for v in m[col]]
        for r in range(n):
            if r != col and m[r][col] != 0.0:
                f = m[r][col]
                m[r] = [rv - f * cv for rv, cv in zip(m[r], m[col], strict=True)]
    return [row[n:] for row in m]


def chol_lower(a: list[list[float]]) -> list[list[float]]:
    """Cholesky-Banachiewicz for SPD matrices (posterior covariance)."""
    n = len(a)
    low = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = a[i][j] - sum(low[i][k] * low[j][k] for k in range(j))
            if i == j:
                low[i][j] = math.sqrt(max(s, 1e-12))
            else:
                low[i][j] = s / low[j][j]
    return low


def ctx_features(ctx: Ctx) -> list[float]:
    """Shared context features for the linear policies: task one-hot (4),
    complexity one-hot (2), and two intercept slots held at 1.0. Arm identity
    lives in the per-arm posteriors (disjoint models), not in the features."""
    feat = [0.0] * len(TASK_TYPES)
    feat[TASK_TYPES.index(ctx.task)] = 1.0
    cx = [0.0] * len(COMPLEXITIES)
    cx[COMPLEXITIES.index(ctx.complexity)] = 1.0
    return [*feat, *cx, 1.0, 1.0]


class LinUCBPolicy(Policy):
    """Disjoint LinUCB: per-arm ridge posterior + optimism bonus."""

    name = "linucb"
    gamma = 0.99  # discounted A, b: stale evidence loses weight

    def __init__(self, seed: int, alpha: float = 0.5) -> None:
        super().__init__(seed)
        self._alpha = alpha
        d = len(ctx_features(Ctx(task="chat", complexity="simple")))
        self._a: list[list[list[float]]] = []
        self._b: list[list[float]] = []
        for _arm in range(N_ARMS):
            eye = [[1.0 if i == j else 0.0 for j in range(d)] for i in range(d)]
            self._a.append(eye)
            self._b.append([0.0] * d)
        self._a_inv = [mat_inverse(m) for m in self._a]
        self._labels = 0

    def _ucb(self, ctx: Ctx, arm: int) -> float:
        x = ctx_features(ctx)
        a_inv = self._a_inv[arm]
        theta = [sum(a_inv[i][j] * self._b[arm][j] for j in range(len(x))) for i in range(len(x))]
        mean = sum(theta[i] * x[i] for i in range(len(x)))
        var = sum(sum(x[i] * a_inv[i][j] for j in range(len(x))) * x[i] for i in range(len(x)))
        return mean + self._alpha * math.sqrt(max(var, 0.0))

    def select(self, ctx: Ctx, usage_pcts: dict[str, float], step: int) -> int:
        # Optimism IS the exploration mechanism here: every selection is
        # exploration-driven by construction, so the unsafe-risk accounting
        # treats all of this policy's deviations as exploration.
        self.last_choice_exploratory = True
        best_arm, best_val = 0, -math.inf
        for arm in range(N_ARMS):
            v = self._ucb(ctx, arm)
            if v > best_val:
                best_arm, best_val = arm, v
        return best_arm

    def observe(self, ctx: Ctx, arm: int, reward: float) -> None:
        x = ctx_features(ctx)
        g = self.gamma
        a = self._a[arm]
        for i in range(len(x)):
            for j in range(len(x)):
                # Discounted update WITH ridge renewal: re-injecting (1-g) on
                # the diagonal keeps the prior at exactly the identity (an
                # easy induction from A₀ = I). Without it the ridge decays as
                # γⁿ, and ctx_features is rank-deficient — the two constant
                # 1.0 slots make the (6,7) block identical — so the singular
                # direction's eigenvalue IS the fading ridge and mat_inverse
                # starts raising ZeroDivisionError after ~2750 labels on one
                # arm. The renewal pins that eigenvalue at 1.0 forever.
                a[i][j] = g * a[i][j] + (1.0 - g) * (1.0 if i == j else 0.0) + x[i] * x[j]
        self._b[arm] = [g * bv + xv * reward for bv, xv in zip(self._b[arm], x, strict=True)]
        self._a_inv[arm] = mat_inverse(a)
        self._labels += 1

    def observed_labels(self) -> int:
        return self._labels


class ThompsonLinearPolicy(Policy):
    """Contextual Thompson sampling with linear-Gaussian posteriors per arm;
    samples theta per selection, argmax of the sampled mean."""

    name = "thompson-linear"
    noise_var = 0.15  # Bernoulli-ish reward variance upper bound
    gamma = 0.99  # discounted A, b: stale evidence loses weight

    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        d = len(ctx_features(Ctx(task="chat", complexity="simple")))
        self._a: list[list[list[float]]] = []
        self._b: list[list[float]] = []
        for _arm in range(N_ARMS):
            eye = [[1.0 if i == j else 0.0 for j in range(d)] for i in range(d)]
            self._a.append(eye)
            self._b.append([0.0] * d)
        self._a_inv: list[list[list[float]] | None] = [None] * N_ARMS
        self._labels = 0

    def _sample_theta(self, arm: int) -> list[float]:
        x_dim = len(self._b[arm])
        if self._a_inv[arm] is None:
            self._a_inv[arm] = mat_inverse(self._a[arm])
        sigma = [[self.noise_var * v for v in row] for row in self._a_inv[arm]]
        low = chol_lower(sigma)
        mu = [
            sum(self._a_inv[arm][i][j] * self._b[arm][j] for j in range(x_dim))
            for i in range(x_dim)
        ]
        z = [self._rng.gauss(0.0, 1.0) for _ in range(x_dim)]
        return [mu[i] + sum(low[i][k] * z[k] for k in range(i + 1)) for i in range(x_dim)]

    def select(self, ctx: Ctx, usage_pcts: dict[str, float], step: int) -> int:
        # Posterior sampling IS the exploration mechanism here: every
        # selection is exploration-driven by construction, so the unsafe-risk
        # accounting treats all of this policy's deviations as exploration.
        self.last_choice_exploratory = True
        x = ctx_features(ctx)
        best_arm, best_val = 0, -math.inf
        for arm in range(N_ARMS):
            theta = self._sample_theta(arm)
            v = sum(theta[i] * x[i] for i in range(len(x)))
            if v > best_val:
                best_arm, best_val = arm, v
        return best_arm

    def observe(self, ctx: Ctx, arm: int, reward: float) -> None:
        x = ctx_features(ctx)
        g = self.gamma
        a = self._a[arm]
        for i in range(len(x)):
            for j in range(len(x)):
                # Ridge renewal as in LinUCBPolicy.observe: without the
                # re-injected (1-g) diagonal the rank-deficient feature block
                # drives A singular (γⁿ below mat_inverse's pivot floor) once
                # one arm accrues enough labels.
                a[i][j] = g * a[i][j] + (1.0 - g) * (1.0 if i == j else 0.0) + x[i] * x[j]
        self._b[arm] = [g * bv + xv * reward for bv, xv in zip(self._b[arm], x, strict=True)]
        self._a_inv[arm] = None  # lazily re-inverted on next selection
        self._labels += 1

    def observed_labels(self) -> int:
        return self._labels


POLICY_FACTORIES: dict[str, Callable[[int], Policy]] = {
    StaticRouterPolicy.name: StaticRouterPolicy,
    CatalogPriorMeanPolicy.name: CatalogPriorMeanPolicy,
    EpsilonGreedyPolicy.name: EpsilonGreedyPolicy,
    LinUCBPolicy.name: LinUCBPolicy,
    ThompsonLinearPolicy.name: ThompsonLinearPolicy,
}


# ─── Episode simulation ──────────────────────────────────────────────────────


class RecoveryTracker:
    """Trailing-window post-drift regret tracker deciding "the policy adapted".

    Adapted = the last ``window`` decisions sit within ``threshold`` expected
    success of the clairvoyant oracle. A trailing window, not cumulative — a
    cumulative post-average dilutes so slowly it can never recover; and 0.03,
    not 0.0, so the floor sits above eps-greedy's own perpetual-exploration
    tax of ~0.016/step.
    """

    def __init__(self, window: int = 100, threshold: float = 0.03) -> None:
        self._window: list[float] = []
        self._window_size = window
        self._threshold = threshold
        self.recovery_step: int | None = None

    def update(self, step: int, regret: float) -> None:
        self._window.append(regret)
        if len(self._window) > self._window_size:
            self._window.pop(0)
        if (
            self.recovery_step is None
            and len(self._window) == self._window_size
            and sum(self._window) / self._window_size <= self._threshold
        ):
            self.recovery_step = step


@dataclass
class RunResult:
    policy: str
    seed: int
    cumulative_regret: float
    regret_rate_pre: float
    regret_rate_post: float
    recovery_step: int | None
    unsafe_total: int
    unsafe_exploration: int
    unsafe_greedy_deviation: int
    unsafe_static: int
    arm_switches: int
    mean_true_quality: float
    mean_list_cost: float
    labels_delivered: int
    labels_dropped: int
    regret_at_labels: dict[str, float] = field(default_factory=dict)


def run_episode(
    policy_name: str,
    seed: int,
    steps: int,
    delay: int,
    label_rate: float,
    drift_at: int,
    checkpoints: Sequence[int],
) -> RunResult:
    """Simulate one policy against the drift world with delayed sparse feedback.

    Regret and quality use expected probabilities (noise-free measurement of
    the policy's decisions); reward *draws* through the channel carry the
    Bernoulli noise the policies must learn through.
    """
    policy = POLICY_FACTORIES[policy_name](seed)
    # Seeded offline-bench PRNG, not a security function (DS148264 note at
    # Policy.__init__ explains why a non-cryptographic generator is the design).
    world_rng = random.Random(seed * 1_000_003 + 17)  # DevSkim: ignore DS148264 until 2027-12-31
    channel = FeedbackChannel(delay, delay, label_rate, world_rng, policy.observe)
    usage: dict[str, float] = {}

    cum_regret = 0.0
    pre_steps = pre_regret = 0
    post_steps = post_regret = 0
    quality_sum = 0.0
    cost_sum = 0.0
    unsafe_total = unsafe_exploration = unsafe_greedy = unsafe_static = 0
    switches = 0
    prev_arm = -1
    tracker = RecoveryTracker()
    regret_at_labels: dict[int, float] = {}
    checkpoint_idx = 0

    for step in range(steps):
        phase = 0 if step < drift_at else 1
        for prov in usage:
            if step % QUOTA_DAY_STEPS == 0:
                usage[prov] = 0.0
        channel.deliver_due(step)

        ctx = sample_context(world_rng)
        usage_pcts = dict(usage)
        arm = policy.select(ctx, usage_pcts, step)

        p_true = true_success_prob(arm, ctx, phase)
        p_best = max(true_success_prob(a, ctx, phase) for a in range(N_ARMS))
        regret = p_best - p_true
        cum_regret += regret
        if phase == 0:
            pre_steps += 1
            pre_regret += regret
        else:
            post_steps += 1
            post_regret += regret
            tracker.update(step, regret)
        quality_sum += p_true
        cost_sum += LIST_COST_PER_1K[arm] * REQUEST_TOKENS / 1000.0

        static_pick = static_router_pick(ctx, usage_pcts)
        if p_true < SAFETY_FLOOR:
            unsafe_total += 1
            if arm == static_pick:
                unsafe_static += 1
            elif policy.last_choice_exploratory:
                unsafe_exploration += 1
            else:
                # Greedy exploitation of a wrong estimate: a deviation from
                # the static pick that came from NO exploration mechanism.
                # Counting it as exploration (the pre-fix behavior) let a
                # pure-greedy policy launder exploitation mistakes into the
                # exploration-risk metric.
                unsafe_greedy += 1
        if prev_arm != -1 and arm != prev_arm:
            switches += 1
        prev_arm = arm

        # The provider's quota drains only for the model actually selected.
        prov = CATALOG[arm][0].provider
        daily = CATALOG[arm][1].free_tokens / 30.0
        usage[prov] = min(1.0, usage.get(prov, 0.0) + REQUEST_TOKENS / daily)

        channel.enqueue(step, ctx, arm, world_rng.random() < p_true)

        while (
            checkpoint_idx < len(checkpoints)
            and policy.observed_labels() >= checkpoints[checkpoint_idx]
        ):
            regret_at_labels[checkpoints[checkpoint_idx]] = round(cum_regret, 4)
            checkpoint_idx += 1

    return RunResult(
        policy=policy_name,
        seed=seed,
        cumulative_regret=round(cum_regret, 4),
        regret_rate_pre=round(pre_regret / max(pre_steps, 1), 6),
        regret_rate_post=round(post_regret / max(post_steps, 1), 6),
        recovery_step=tracker.recovery_step,
        unsafe_total=unsafe_total,
        unsafe_exploration=unsafe_exploration,
        unsafe_greedy_deviation=unsafe_greedy,
        unsafe_static=unsafe_static,
        arm_switches=switches,
        mean_true_quality=round(quality_sum / steps, 6),
        mean_list_cost=round(cost_sum / steps, 6),
        labels_delivered=channel.delivered,
        labels_dropped=channel.dropped,
        regret_at_labels={str(k): v for k, v in sorted(regret_at_labels.items())},
    )


# ─── Logged dataset generation + off-policy evaluation ───────────────────────


@dataclass(frozen=True)
class LogRow:
    ctx: Ctx
    arm: int
    reward: float
    propensity: float


# Flat provider-usage prior for offline log replay: no quota pressure in the
# logged world, matching the static router's no-quota baseline behavior.
LOG_USAGE_PCTS: dict[str, float] = dict.fromkeys(("alpha", "beta", "gamma"), 0.05)


def generate_logged_dataset(n: int, eps: float, seed: int, phase: int = 0) -> list[LogRow]:
    """Eps-greedy static-router logging policy with recorded propensities.

    p(a|x) = (1-eps)·1{a = static_pick} + eps/N — the bias later corrected by
    IPS clipping. Rewards are Bernoulli draws of the true outcome model.
    """
    # Seeded offline-bench PRNG, not a security function (DS148264 note at
    # Policy.__init__ explains why a non-cryptographic generator is the design).
    rng = random.Random(seed * 7_919 + 101)  # DevSkim: ignore DS148264 until 2027-12-31
    rows: list[LogRow] = []
    for _ in range(n):
        ctx = sample_context(rng)
        pick = static_router_pick(ctx, LOG_USAGE_PCTS)
        arm = rng.randrange(N_ARMS) if rng.random() < eps else pick
        propensity = (1.0 - eps) * float(arm == pick) + eps / N_ARMS
        reward = 1.0 if rng.random() < true_success_prob(arm, ctx, phase) else 0.0
        rows.append(LogRow(ctx=ctx, arm=arm, reward=reward, propensity=propensity))
    return rows


def fit_on_log(policy: Policy, rows: Sequence[LogRow]) -> None:
    """Offline batch fit: every logged row's feedback is delivered immediately."""
    for row in rows:
        policy.observe(row.ctx, row.arm, row.reward)


def direct_model_fit(
    train_rows: Sequence[LogRow], prior_weight: float = 4.0
) -> Callable[[Ctx, int], float]:
    """Smoothed per-(cell, arm) outcome model for doubly-robust evaluation."""
    sums: dict[tuple[tuple[str, str], int], float] = {}
    counts: dict[tuple[tuple[str, str], int], int] = {}
    for row in train_rows:
        k = (row.ctx.key(), row.arm)
        sums[k] = sums.get(k, 0.0) + row.reward
        counts[k] = counts.get(k, 0) + 1
    global_mean = sum(r.reward for r in train_rows) / max(len(train_rows), 1)

    def model(ctx: Ctx, arm: int) -> float:
        k = (ctx.key(), arm)
        n = counts.get(k, 0)
        if n == 0:
            return global_mean
        return (sums[k] + prior_weight * global_mean) / (n + prior_weight)

    return model


@dataclass(frozen=True)
class OpeResult:
    policy: str
    ips: float
    dr: float
    true_value: float
    ips_abs_bias: float
    dr_abs_bias: float
    clip_rate: float


def evaluate_ope(
    policy: Policy,
    eval_rows: Sequence[LogRow],
    train_rows: Sequence[LogRow],
    clip_min: float = 0.05,
) -> OpeResult:
    """Clipped IPS and doubly-robust estimates vs known truth.

    Propensity bias is handled the standard ways — recorded propensities, IPS
    weighting, clipping against the heavy tail of 1/p — and the residual bias
    is *measured* against the ground-truth value rather than assumed away.

    The truth is the exact expected success of the very actions the policy
    took on these eval rows (common random numbers): re-rolling a stochastic
    policy (eps-greedy's ε-draws, Thompson's posterior samples) would measure
    Monte-Carlo disagreement between two target rollouts, not estimator bias.
    """
    model = direct_model_fit(train_rows)
    ips_sum = 0.0
    dr_sum = 0.0
    truth_sum = 0.0
    clipped = 0
    for row in eval_rows:
        chosen = policy.select(row.ctx, LOG_USAGE_PCTS, 10**9)
        truth_sum += true_success_prob(chosen, row.ctx, phase=0)
        if row.arm == chosen:
            p = max(row.propensity, clip_min)
            if row.propensity < clip_min:
                clipped += 1
            w = 1.0 / p
            ips_sum += w * row.reward
            dr_sum += (row.reward - model(row.ctx, chosen)) * w
        dr_sum += model(row.ctx, chosen)
    n = max(len(eval_rows), 1)
    truth = truth_sum / n
    ips = ips_sum / n
    dr = dr_sum / n
    return OpeResult(
        policy=policy.name,
        ips=round(ips, 6),
        dr=round(dr, 6),
        true_value=round(truth, 6),
        ips_abs_bias=round(abs(ips - truth), 6),
        dr_abs_bias=round(abs(dr - truth), 6),
        clip_rate=round(clipped / n, 6),
    )


# ─── Aggregation + reporting ─────────────────────────────────────────────────


def aggregate(
    results: Sequence[RunResult],
) -> dict[str, dict[str, float | int | None]]:
    """Per-policy mean and (sample) std across seeds for the headline metrics."""
    by_policy: dict[str, list[RunResult]] = {}
    for r in results:
        by_policy.setdefault(r.policy, []).append(r)
    out: dict[str, dict[str, float | int | None]] = {}
    for name, rs in by_policy.items():

        def stat(runs: list[RunResult], pick: Callable[[RunResult], float]) -> dict[str, float]:
            vals = [pick(r) for r in runs]
            mean = sum(vals) / len(vals)
            # Sample standard deviation (n-1): the advertised dispersion of a
            # 5-seed sample; the population denominator understated every
            # displayed std by ~10.6%.
            var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1) if len(vals) > 1 else 0.0
            return {"mean": round(mean, 6), "std": round(math.sqrt(var), 6)}

        recoveries = [r.recovery_step for r in rs if r.recovery_step is not None]
        out[name] = {
            "cumulative_regret": stat(rs, lambda r: r.cumulative_regret),
            "regret_rate_pre": stat(rs, lambda r: r.regret_rate_pre),
            "regret_rate_post": stat(rs, lambda r: r.regret_rate_post),
            "unsafe_total": stat(rs, lambda r: float(r.unsafe_total)),
            "unsafe_exploration": stat(rs, lambda r: float(r.unsafe_exploration)),
            "unsafe_greedy_deviation": stat(rs, lambda r: float(r.unsafe_greedy_deviation)),
            "unsafe_static": stat(rs, lambda r: float(r.unsafe_static)),
            "arm_switches": stat(rs, lambda r: float(r.arm_switches)),
            "mean_true_quality": stat(rs, lambda r: r.mean_true_quality),
            "mean_list_cost": stat(rs, lambda r: r.mean_list_cost),
            "recovery_step_mean": (
                round(sum(recoveries) / len(recoveries), 1) if recoveries else None
            ),
            "recovery_step_hits": f"{len(recoveries)}/{len(rs)}",
            "labels_delivered": stat(rs, lambda r: float(r.labels_delivered)),
        }
    return out


def pareto_flags(
    agg: dict[str, dict[str, float | int | None]],
) -> dict[str, bool]:
    """A policy is on the quality/cost frontier if no other policy dominates
    it (higher mean quality AND lower-or-equal mean cost, strictly better in
    one)."""
    quality = {k: v["mean_true_quality"]["mean"] for k, v in agg.items()}  # type: ignore[index]
    cost = {k: v["mean_list_cost"]["mean"] for k, v in agg.items()}  # type: ignore[index]
    flags: dict[str, bool] = {}
    for name in agg:
        dominated = any(
            other != name
            and quality[other] >= quality[name]
            and cost[other] <= cost[name]
            and (quality[other] > quality[name] or cost[other] < cost[name])
            for other in agg
        )
        flags[name] = not dominated
    return flags


def run_bench(
    steps: int,
    seeds: Sequence[int],
    delay: int,
    label_rate: float,
    drift_at: int,
) -> dict:
    """Full bench: episodes for every policy x seed, then OPE on a held-out log."""
    checkpoints = [100, 300, 600, 1200, 2400]
    results: list[RunResult] = []
    for name in POLICY_FACTORIES:
        for seed in seeds:
            results.append(run_episode(name, seed, steps, delay, label_rate, drift_at, checkpoints))
    agg = aggregate(results)

    log_rows = generate_logged_dataset(2000, eps=0.2, seed=seeds[0], phase=0)
    split = int(len(log_rows) * 0.6)
    train_rows, eval_rows = log_rows[:split], log_rows[split:]
    ope: dict[str, OpeResult] = {}
    for name, factory in POLICY_FACTORIES.items():
        policy = factory(seeds[0])
        fit_on_log(policy, train_rows)
        ope[name] = evaluate_ope(policy, eval_rows, train_rows)

    sample_efficiency: dict[str, dict[str, float]] = {}
    for name in POLICY_FACTORIES:
        runs = [r for r in results if r.policy == name]
        # Mean regret-at-checkpoint ACROSS seeds: picking the first matching
        # run silently reported seed 0 alone, so --seeds changed nothing here
        # and one noisy seed could decide the sample-efficiency ordering.
        per_checkpoint: dict[int, list[float]] = {}
        for r in runs:
            for checkpoint, regret in r.regret_at_labels.items():
                per_checkpoint.setdefault(int(checkpoint), []).append(regret)
        sample_efficiency[name] = {
            str(checkpoint): round(sum(vals) / len(vals), 4)
            for checkpoint, vals in sorted(per_checkpoint.items())
        }
    return {
        "config": {
            "steps": steps,
            "seeds": list(seeds),
            "delay": delay,
            "label_rate": label_rate,
            "drift_at": drift_at,
            "safety_floor": SAFETY_FLOOR,
            "request_tokens": REQUEST_TOKENS,
        },
        "per_policy": agg,
        "pareto_on_frontier": pareto_flags(agg),
        "off_policy_evaluation": {
            k: vars(v) if not isinstance(v, dict) else v for k, v in ope.items()
        },
        "sample_efficiency": sample_efficiency,
        "run_results": [vars(r) for r in results],
    }


def print_report(report: dict) -> None:
    per = report["per_policy"]
    order = [
        StaticRouterPolicy.name,
        CatalogPriorMeanPolicy.name,
        EpsilonGreedyPolicy.name,
        LinUCBPolicy.name,
        ThompsonLinearPolicy.name,
    ]
    cfg = report["config"]
    print(
        f"\n=== offline model-routing bench (steps={cfg['steps']}, "
        f"seeds={cfg['seeds']}, delay={cfg['delay']}, label_rate={cfg['label_rate']}, "
        f"drift_at={cfg['drift_at']}) ==="
    )
    hdr = (
        f"{'policy':<18}{'regret±':<16}{'pre-rate':<10}{'post-rate':<10}"
        f"{'recover':<10}{'unsafeE':<9}{'unsafeG':<9}{'quality':<9}{'cost':<7}{'frontier'}"
    )
    print(hdr)
    for name in order:
        if name not in per:
            continue
        p = per[name]
        reg = p["cumulative_regret"]
        frontier = "yes" if report["pareto_on_frontier"][name] else "no"
        print(
            f"{name:<18}"
            f"{reg['mean']:.0f}±{reg['std']:.0f}    "
            f"{p['regret_rate_pre']['mean']:.4f}   "
            f"{p['regret_rate_post']['mean']:.4f}   "
            f"{p['recovery_step_mean']!s:<10}"
            f"{p['unsafe_exploration']['mean']:<9.1f}"
            f"{p['unsafe_greedy_deviation']['mean']:<9.1f}"
            f"{p['mean_true_quality']['mean']:.4f}  "
            f"{p['mean_list_cost']['mean']:.3f}  "
            f"{frontier}"
        )
    print("\n--- off-policy evaluation on held-out eps-greedy static-router log (pre-drift) ---")
    for name in order:
        o = report["off_policy_evaluation"].get(name)
        if o is None:
            continue
        print(
            f"{name:<18} ips={o['ips']:.4f} (|bias| {o['ips_abs_bias']:.4f})  "
            f"dr={o['dr']:.4f} (|bias| {o['dr_abs_bias']:.4f})  "
            f"truth={o['true_value']:.4f}  clip_rate={o['clip_rate']:.3f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--delay", type=int, default=25)
    ap.add_argument("--label-rate", type=float, default=0.8)
    ap.add_argument("--drift-at", type=int, default=700)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    # A run with no post-drift phase would report a perfect-looking
    # regret_rate_post of 0.0 (and never recover), and an empty seed list
    # would crash the OPE stage on seeds[0] — both fail loudly here instead.
    if not 0 < args.drift_at < args.steps:
        ap.error(
            f"--drift-at must satisfy 0 < drift-at < steps "
            f"(got drift-at={args.drift_at}, steps={args.steps}); a run with "
            f"no post-drift phase would report regret_rate_post=0.0"
        )
    if args.seeds < 1:
        ap.error(f"--seeds must be >= 1 (got {args.seeds}); there would be no episodes to run")

    report = run_bench(
        steps=args.steps,
        seeds=list(range(args.seeds)),
        delay=args.delay,
        label_rate=args.label_rate,
        drift_at=args.drift_at,
    )
    print_report(report)
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"\nfull results written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
