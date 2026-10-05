#!/usr/bin/env python3
"""Task-conditioned model-routing benchmark (issue #914, epic #900 M8-B1).

Offline/replay evaluator comparing the shipped static router against
task-conditioned routing policies over one shared task corpus and one shared,
policy-independent outcome table.

What is real
------------
The routing seam is the shipped one: `CostAwareRouter.select(task, budget)`
over an `InMemoryProviderRegistry` (ADR-079) — the selection path production
uses (`maistro.capabilities.model_chat.resolve_model_chat_provider`) — plus
registry availability and `compute_cost_cents`. Policies are selection
functions over that same registry.

What is simulated (and said so loudly)
--------------------------------------
The repository records no per-task routing telemetry, so outcomes (success,
realized latency, output tokens) come from a fixed deterministic outcome model
over (task, model) pairs. The outcome table is built ONCE, before any policy
runs — every policy is scored against the identical table, so comparisons
between policies are exact. Magnitudes are simulator-dependent; the structural
findings (what the seam can and cannot express) are not.

Policies
--------
- shipped-router     : the production baseline. `CostAwareRouter.select` with a
                       bare task descriptor and an unconstrained budget — the
                       exact call shape of every production caller. The router
                       ignores the task descriptor (it sorts by latency_p50_ms),
                       so this policy is "fastest available model, always".
- static-cheap       : the one conditioning lever the seam offers today without
                       per-task information — a static `RouterBudget`
                       (max_cost_cents) set once for the whole corpus. Still
                       the real router.
- budget-conditioned : per-task `RouterBudget` derived from observable task
                       features, selection still via the real router. Shows
                       what the budget seam can express (reasoning, cost caps)
                       and what it cannot (context capacity — `RouterBudget`
                       has no field for it).
- tier-conditioned   : minimal task-conditioned router: observable features map
                       to an allowed tier set; selection within the set keeps
                       the shipped preference (lowest latency_p50_ms among
                       available models). A candidate policy — NOT wired into
                       production (the issue forbids that).
- oracle             : per-task argmax of realized utility over the outcome
                       table — "chosen after outcomes", the regret baseline.

Measured (per the issue)
------------------------
success, cost, realized p50/p95 latency and deadline misses, provider/model
concentration (shares + HHI), routing stability (selection flip rate under
bounded feature jitter), feature leakage (routing decisions must be invariant
to the outcome realization; the oracle is the positive control that proves the
detector can fire), and regret versus the oracle.

Deterministic and offline: every random draw is a blake2b hash of stable ids;
no network, no database. Run it after changing routing, the model catalog, or
the outcome model; results are comparable run-to-run.

Usage:
    uv run python scripts/bench_model_routing.py [--tasks-per-class 400]
        [--seed routing-bench-v1] [--scenario all-available|opus-degraded]
        [--output results.json]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "maistro-core" / "src"))

from maistro.providers import (
    CostAwareRouter,
    InMemoryProviderRegistry,
    ModelMetadata,
    NoEligibleModelError,
    RouterBudget,
    RoutingTask,
    compute_cost_cents,
)

# --------------------------------------------------------------------------
# Model catalog. Mirrors packages/maistro-core/tests/providers/fixtures_models.py
# (the catalog the routing tests assert against), extended with a balanced-tier
# model and explicit max_tokens so context-capacity conditioning has something
# to bite on. Costs are cents per 1k tokens, as ModelMetadata defines.
# --------------------------------------------------------------------------


def _catalog() -> list[ModelMetadata]:
    return [
        ModelMetadata(
            name="claude-3-opus",
            provider="anthropic",
            tier="powerful",
            cost_per_1k_input=0.15,
            cost_per_1k_output=0.75,
            latency_p50_ms=800,
            reasoning_capable=True,
            max_tokens=200_000,
            fallback_to=("gpt-4-turbo",),
        ),
        ModelMetadata(
            name="gpt-4-turbo",
            provider="openai",
            tier="powerful",
            cost_per_1k_input=0.03,
            cost_per_1k_output=0.06,
            latency_p50_ms=1200,
            max_tokens=32_768,
            fallback_to=("gpt-3.5-turbo",),
        ),
        ModelMetadata(
            name="gpt-4o-mini",
            provider="openai",
            tier="balanced",
            cost_per_1k_input=0.005,
            cost_per_1k_output=0.015,
            latency_p50_ms=600,
            max_tokens=16_384,
            fallback_to=("gpt-3.5-turbo",),
        ),
        ModelMetadata(
            name="gpt-3.5-turbo",
            provider="openai",
            tier="fast",
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
            latency_p50_ms=400,
            max_tokens=4_096,
        ),
        ModelMetadata(
            name="local-llama",
            provider="local",
            tier="fast",
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            latency_p50_ms=2500,
            max_tokens=8_192,
        ),
    ]


# --------------------------------------------------------------------------
# Task corpus: observable features a routing policy may condition on, plus a
# HIDDEN per-task difficulty that only the outcome model sees. A policy that
# used difficulty would be leaking the outcome into the decision; the corpus
# types make that structurally impossible (Task carries no difficulty field)
# and the leakage audit checks decision-invariance empirically.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """Observable task descriptor — the only thing a policy may condition on.

    `task_type` mirrors `RoutingTask.task_type`; the remaining fields are the
    task features the issue names (capability class, tool use, context size,
    latency budget). A production caller could populate every field from the
    graph NodeRun payload; none of them are outcome data.
    """

    task_id: str
    task_type: str  # capability class
    context_tokens: int
    expected_output_tokens: int
    tool_use: bool
    reasoning_required: bool
    latency_budget_ms: int


@dataclass(frozen=True)
class TaskCase:
    """Corpus row: the observable task plus hidden ground-truth difficulty."""

    task: Task
    difficulty: float  # in [0, 1]; outcome-model input, never policy input


@dataclass(frozen=True)
class ClassSpec:
    """Per-capability-class corpus parameters: difficulty range, latency SLO,
    reasoning and tool-use rates. The classes and rough weights follow the
    workload the graph nodes and Agent strategies serve: conversational turns
    and classification are common and easy; summarization is context-heavy;
    code repair and planning are hard and often need reasoning."""

    difficulty: tuple[float, float]
    slo_ms: float
    reasoning: float
    tools: float


TASK_CLASSES: dict[str, ClassSpec] = {
    "chat": ClassSpec(difficulty=(0.05, 0.40), slo_ms=1500, reasoning=0.0, tools=0.05),
    "classification": ClassSpec(difficulty=(0.05, 0.45), slo_ms=2000, reasoning=0.0, tools=0.0),
    "extraction": ClassSpec(difficulty=(0.25, 0.65), slo_ms=3000, reasoning=0.05, tools=0.10),
    "summarization": ClassSpec(difficulty=(0.25, 0.60), slo_ms=5000, reasoning=0.0, tools=0.0),
    "code_repair": ClassSpec(difficulty=(0.55, 0.95), slo_ms=8000, reasoning=0.70, tools=0.40),
    "planning": ClassSpec(difficulty=(0.55, 0.95), slo_ms=8000, reasoning=0.85, tools=0.20),
}
CLASS_NAMES = tuple(TASK_CLASSES)

#: context tokens are drawn log-uniformly in a class-dependent band.
CONTEXT_BANDS: dict[str, tuple[int, int]] = {
    "chat": (400, 4_000),
    "classification": (300, 6_000),
    "extraction": (1_000, 20_000),
    "summarization": (4_000, 60_000),
    "code_repair": (1_000, 25_000),
    "planning": (1_500, 15_000),
}
OUTPUT_BANDS: dict[str, tuple[int, int]] = {
    "chat": (80, 400),
    "classification": (5, 40),
    "extraction": (100, 800),
    "summarization": (200, 1_200),
    "code_repair": (100, 900),
    "planning": (300, 1_500),
}


def _hash_float(*parts: object) -> float:
    """Deterministic uniform draw in [0, 1) from stable string parts."""
    digest = hashlib.blake2b("|".join(str(p) for p in parts).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def make_task(seed: str, class_name: str, index: int) -> TaskCase:
    """One deterministic corpus row. Same (seed, class, index) -> same task."""
    spec = TASK_CLASSES[class_name]
    c_lo, c_hi = CONTEXT_BANDS[class_name]
    o_lo, o_hi = OUTPUT_BANDS[class_name]

    def u(tag: str) -> float:
        return _hash_float(seed, class_name, index, tag)

    # Log-uniform context: real contexts span orders of magnitude.
    ctx = int(math.exp(_lerp(math.log(c_lo), math.log(c_hi), u("ctx"))))
    out = int(_lerp(o_lo, o_hi, u("out")))
    return TaskCase(
        task=Task(
            task_id=f"{class_name}-{index:05d}",
            task_type=class_name,
            context_tokens=ctx,
            expected_output_tokens=out,
            tool_use=u("tools") < spec.tools,
            reasoning_required=u("reasoning") < spec.reasoning,
            latency_budget_ms=int(_lerp(0.75, 1.5, u("slo")) * spec.slo_ms),
        ),
        difficulty=_lerp(spec.difficulty[0], spec.difficulty[1], u("difficulty")),
    )


def make_corpus(seed: str, tasks_per_class: int) -> list[TaskCase]:
    return [
        make_task(seed, class_name, i) for class_name in CLASS_NAMES for i in range(tasks_per_class)
    ]


def jittered_twin(case: TaskCase, seed: str) -> TaskCase:
    """Same task with context/output perturbed by at most ±5%.

    Stability probe: a policy whose selection flips on a bounded
    re-measurement of context size is unstable. Difficulty is untouched — the
    outcome table entry is unchanged, so only the routing input moves.
    """
    t = case.task

    def j(tag: str) -> float:
        return 0.95 + 0.10 * _hash_float(seed, t.task_id, tag)

    twin = Task(
        task_id=t.task_id,
        task_type=t.task_type,
        context_tokens=max(1, int(t.context_tokens * j("ctx"))),
        expected_output_tokens=max(1, int(t.expected_output_tokens * j("out"))),
        tool_use=t.tool_use,
        reasoning_required=t.reasoning_required,
        latency_budget_ms=t.latency_budget_ms,
    )
    return TaskCase(task=twin, difficulty=case.difficulty)


# --------------------------------------------------------------------------
# Outcome model: a pure function of (task case, model) — independent of every
# policy. Built once, before routing, as a table keyed by (task_id, model);
# policies are scored by table lookup, which makes the cross-policy comparison
# exact and the leakage audit decidable.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    success: bool
    latency_ms: float
    output_tokens: int
    cost_cents: float
    deadline_miss: bool

    @property
    def utility(self) -> float:
        """Composite utility. Success dominates; cost and latency are real but
        secondary. Weights are a documented modeling choice — the raw metrics
        are reported alongside, so no conclusion hinges on them alone."""
        util = (1.0 if self.success else -0.25) - 0.05 * self.cost_cents
        return util - 0.0002 * self.latency_ms


#: Base success on a task inside the tier's comfort zone, and the difficulty
#: up to which the tier is comfortable. The escalation shape is the empirical
#: regularity the hypothesis rests on: cheap models are fine on easy work and
#: fall off a cliff past their comfort zone; capable models degrade gently.
#: (Simulator assumptions — published benchmark-and-price sheets are the
#: qualitative source; the numbers are modeling choices, stated here.)
TIER_COMFORT = {"fast": 0.35, "balanced": 0.60, "powerful": 0.90}
TIER_BASE_SUCCESS = {"fast": 0.92, "balanced": 0.95, "powerful": 0.97}
#: Difficulty beyond the comfort zone costs this much success probability
#: per unit of difficulty — the cliff.
DIFFICULTY_SLOPE = 0.90


def simulate_outcome(
    case: TaskCase, model: ModelMetadata, seed: str = "routing-bench-v1"
) -> Outcome:
    """Deterministic (task, model) -> Outcome. Sees no policy, holds no RNG."""
    task = case.task

    def u(tag: str) -> float:
        return _hash_float(seed, "outcome", task.task_id, model.name, tag)

    # Hard capacity bound from registry metadata: a model cannot emit more
    # tokens than its context window allows. Registry facts, not simulator
    # opinion.
    if task.context_tokens + task.expected_output_tokens > model.max_tokens:
        return Outcome(
            success=False,
            latency_ms=float(model.latency_p50_ms),
            output_tokens=0,
            cost_cents=0.0,
            deadline_miss=model.latency_p50_ms > task.latency_budget_ms,
        )

    p = TIER_BASE_SUCCESS[model.tier] - DIFFICULTY_SLOPE * max(
        0.0, case.difficulty - TIER_COMFORT[model.tier]
    )
    if task.reasoning_required:
        p += 0.05 if model.reasoning_capable else -0.25
    if task.tool_use:
        p -= 0.08
    p = min(0.98, max(0.02, p))
    success = u("success") < p

    # Realized latency: p50 scaled by context load and ±30% run noise.
    context_load = 1.0 + task.context_tokens / 50_000
    latency = model.latency_p50_ms * context_load * (0.7 + 0.6 * u("latency"))
    out_tokens = int(task.expected_output_tokens * (0.8 + 0.4 * u("tokens")))
    in_tokens = min(task.context_tokens, model.max_tokens)
    cost = compute_cost_cents(model, in_tokens, out_tokens)
    return Outcome(
        success=success,
        latency_ms=latency,
        output_tokens=out_tokens,
        cost_cents=cost,
        deadline_miss=latency > task.latency_budget_ms,
    )


OutcomeTable = dict[tuple[str, str], Outcome]


async def build_outcome_table(
    corpus: list[TaskCase], registry: InMemoryProviderRegistry, seed: str
) -> OutcomeTable:
    """Precompute the outcome of every (task, model) pair. Built once, before
    any policy runs: every policy is scored against the identical table."""
    models = await registry.list_models()
    return {
        (case.task.task_id, model.name): simulate_outcome(case, model, seed)
        for case in corpus
        for model in models
    }


# --------------------------------------------------------------------------
# Policies. A policy sees a Task (observable features) and the registry; it
# never sees TaskCase.difficulty or the outcome table — except the oracle,
# which is defined as choosing after outcomes and serves as the leakage
# detector's positive control.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutedCall:
    model_name: str
    policy: str


class RoutingPolicy:
    """Selection over the real registry seam. Outcome-blind by construction."""

    name = "policy"

    def __init__(self, registry: InMemoryProviderRegistry) -> None:
        self.registry = registry
        self.route_failures = 0

    async def available(self) -> list[ModelMetadata]:
        models = await self.registry.list_models()
        return [m for m in models if self.registry.is_available(m.name)]

    async def select(self, task: Task) -> ModelMetadata:
        raise NotImplementedError

    async def route(self, task: Task) -> RoutedCall | None:
        try:
            model = await self.select(task)
        except NoEligibleModelError:
            self.route_failures += 1
            return None
        return RoutedCall(model_name=model.name, policy=self.name)


class ShippedRouterPolicy(RoutingPolicy):
    """The production baseline: CostAwareRouter, bare task descriptor,
    unconstrained budget — the exact call shape of
    `maistro.capabilities.model_chat.resolve_model_chat_provider`."""

    name = "shipped-router"

    def __init__(
        self,
        registry: InMemoryProviderRegistry,
        router: CostAwareRouter,
        budget: RouterBudget | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(registry)
        self.router = router
        self.budget = budget
        if name is not None:
            self.name = name

    async def select(self, task: Task) -> ModelMetadata:
        return await self.router.select(RoutingTask(task_type=task.task_type), self.budget)


#: Static cheap tier: a whole-corpus cost cap — the one conditioning lever the
#: shipped seam offers today without per-task information — pushed to its
#: zero-incremental-cost extreme (only free models remain eligible). A looser
#: cap (e.g. 0.01) selects identically to the shipped router, because the
#: latency-first preference already picks the cheapest fast model; the cap
#: only bites once it excludes the latency-winner.
STATIC_CHEAP_BUDGET = RouterBudget(max_cost_cents=0.0)

#: Conditioning thresholds shared by the two conditioned policies. Selection
#: inside an allowed set keeps the shipped preference order (lowest
#: latency_p50_ms among available models) so the comparison isolates
#: conditioning, not preference.
CONDITIONING_HARD_TYPES = frozenset({"code_repair", "planning"})
CONDITIONING_HEAVY_CONTEXT_TOKENS = 12_000

#: Budget-conditioned policy caps. `RouterBudget` can express reasoning and
#: cost caps; it has NO capacity field, so large-context tasks cannot be
#: protected here — that limitation is a finding the benchmark measures, not a
#: bug in the benchmark.
BUDGET_CONDITIONED_EASY_CAP = RouterBudget(max_cost_cents=0.01)
BUDGET_CONDITIONED_HARD_CAP = RouterBudget(max_cost_cents=0.2)


class BudgetConditionedPolicy(ShippedRouterPolicy):
    """Features -> per-task RouterBudget -> the real CostAwareRouter."""

    name = "budget-conditioned"

    async def select(self, task: Task) -> ModelMetadata:
        if task.reasoning_required:
            budget = RouterBudget(reasoning=True)
        elif task.task_type in CONDITIONING_HARD_TYPES:
            budget = BUDGET_CONDITIONED_HARD_CAP
        else:
            budget = BUDGET_CONDITIONED_EASY_CAP
        return await self.router.select(RoutingTask(task_type=task.task_type), budget)


def _allowed_tiers(task: Task) -> frozenset[str]:
    """Observable features -> allowed tier set (the conditioning function)."""
    if task.reasoning_required or task.task_type in CONDITIONING_HARD_TYPES:
        return frozenset({"powerful"})
    if task.context_tokens + task.expected_output_tokens > CONDITIONING_HEAVY_CONTEXT_TOKENS:
        return frozenset({"balanced", "powerful"})
    return frozenset({"fast", "balanced"})


class TierConditionedPolicy(RoutingPolicy):
    """Features -> capacity floor + allowed tier set -> shipped preference.

    Capacity is a hard constraint read from registry metadata (a model whose
    window cannot hold the task hard-fails in any outcome model); the tier set
    is the conditioned preference. Selection keeps the shipped order (lowest
    latency_p50_ms among available models), falling back to any
    capacity-adequate model when the preferred tiers cannot fit the task.
    Uses only real registry seams (`list_models`, `is_available`). It is a
    candidate policy evaluated offline, not production code."""

    name = "tier-conditioned"

    async def select(self, task: Task) -> ModelMetadata:
        demand = task.context_tokens + task.expected_output_tokens
        capable = [m for m in await self.available() if m.max_tokens >= demand]
        if not capable:
            raise NoEligibleModelError(detail=f"no available model with capacity {demand}")
        allowed = _allowed_tiers(task)
        tier_pool = [m for m in capable if m.tier in allowed] or capable
        return min(tier_pool, key=lambda m: m.latency_p50_ms)


class OraclePolicy(RoutingPolicy):
    """Per-task argmax of realized utility over the outcome table. Upper bound
    by definition; the regret baseline ("chosen after outcomes")."""

    name = "oracle"

    def __init__(
        self,
        registry: InMemoryProviderRegistry,
        outcomes: OutcomeTable,
    ) -> None:
        super().__init__(registry)
        self.outcomes = outcomes

    async def select(self, task: Task) -> ModelMetadata:
        available = await self.available()
        if not available:
            raise NoEligibleModelError(detail="no available models")
        return max(available, key=lambda m: self.outcomes[(task.task_id, m.name)].utility)


# --------------------------------------------------------------------------
# Metrics.
# --------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[max(index, 0)]


def _hhi(shares: dict[str, float]) -> float:
    """Herfindahl-Hirschman concentration index: sum of squared shares."""
    return sum(s * s for s in shares.values())


@dataclass
class PolicyReport:
    policy: str
    routed: int
    route_failures: int
    success_rate: float
    cost_cents_total: float
    cost_cents_per_task: float
    cost_cents_per_success: float
    latency_p50_ms: float
    latency_p95_ms: float
    deadline_miss_rate: float
    mean_utility: float
    model_shares: dict[str, float] = field(default_factory=dict)
    provider_shares: dict[str, float] = field(default_factory=dict)
    model_hhi: float = 0.0
    provider_hhi: float = 0.0


def score_policy(
    name: str,
    routed: list[tuple[TaskCase, str | None]],
    metadata: dict[str, ModelMetadata],
    outcomes: OutcomeTable,
    route_failures: int,
) -> PolicyReport:
    """Aggregate one policy's routing decisions against the shared table."""
    latencies: list[float] = []
    costs = 0.0
    successes = 0
    utilities = 0.0
    misses = 0
    model_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    total = 0
    for case, model_name in routed:
        total += 1
        if model_name is None:
            # Route failure = no model at all: the worst outcome, priced as
            # such so route failures can never look cheap.
            utilities += Outcome(
                success=False,
                latency_ms=0.0,
                output_tokens=0,
                cost_cents=0.0,
                deadline_miss=True,
            ).utility
            misses += 1
            continue
        outcome = outcomes[(case.task.task_id, model_name)]
        latencies.append(outcome.latency_ms)
        costs += outcome.cost_cents
        utilities += outcome.utility
        misses += outcome.deadline_miss
        successes += outcome.success
        model_counts[model_name] = model_counts.get(model_name, 0) + 1
        provider = metadata[model_name].provider
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
    n = max(total, 1)
    ok = max(successes, 1)
    model_shares = {k: v / n for k, v in model_counts.items()}
    provider_shares = {k: v / n for k, v in provider_counts.items()}
    return PolicyReport(
        policy=name,
        routed=total,
        route_failures=route_failures,
        success_rate=successes / n,
        cost_cents_total=round(costs, 4),
        cost_cents_per_task=round(costs / n, 6),
        cost_cents_per_success=round(costs / ok, 6),
        latency_p50_ms=round(_percentile(latencies, 50), 1),
        latency_p95_ms=round(_percentile(latencies, 95), 1),
        deadline_miss_rate=round(misses / n, 4),
        mean_utility=round(utilities / n, 4),
        model_shares={k: round(v, 4) for k, v in sorted(model_shares.items())},
        provider_shares={k: round(v, 4) for k, v in sorted(provider_shares.items())},
        model_hhi=round(_hhi(model_shares), 4),
        provider_hhi=round(_hhi(provider_shares), 4),
    )


async def route_all(
    policy: RoutingPolicy, corpus: list[TaskCase]
) -> list[tuple[TaskCase, str | None]]:
    """Route every task; collect (case, model_name) with None on route
    failure. Routing order is corpus order and every policy here is stateless,
    but decisions are collected per-task so order can never matter."""
    routed: list[tuple[TaskCase, str | None]] = []
    for case in corpus:
        call = await policy.route(case.task)
        routed.append((case, call.model_name if call else None))
    return routed


async def selection_flip_rate(
    policy: RoutingPolicy, corpus: list[TaskCase], twin_seed: str
) -> float:
    """Fraction of tasks whose routed model changes under bounded jitter of
    observable features (±5% context/output; outcomes unchanged)."""
    flips = 0
    for case in corpus:
        base = await policy.route(case.task)
        twin = jittered_twin(case, twin_seed)
        again = await policy.route(twin.task)
        if base is not None and again is not None and base.model_name != again.model_name:
            flips += 1
    return flips / max(len(corpus), 1)


async def leakage_audit(
    policy: RoutingPolicy,
    corpus: list[TaskCase],
    registry: InMemoryProviderRegistry,
    seed: str,
) -> int:
    """Count tasks whose selection changes when ONLY the outcome realization
    is re-seeded. A well-posed routing policy is outcome-blind: regenerating
    the table must not move its decisions. (The oracle — the one policy that
    reads the table — is the positive control: run through the same audit, it
    must move, which is what proves the detector can fire.)"""
    alt_table = await build_outcome_table(corpus, registry, seed + "|leakage-audit")
    if isinstance(policy, OraclePolicy):
        original = policy.outcomes
        policy.outcomes = alt_table
        try:
            alt_routed = await route_all(policy, corpus)
        finally:
            policy.outcomes = original
        base_routed = await route_all(policy, corpus)
    else:
        alt_routed = await route_all(policy, corpus)
        base_routed = await route_all(policy, corpus)
    violations = 0
    for (base_case, base_model), (alt_case, alt_model) in zip(base_routed, alt_routed, strict=True):
        assert base_case.task.task_id == alt_case.task.task_id
        if base_model != alt_model:
            violations += 1
    return violations


# --------------------------------------------------------------------------
# Benchmark driver.
# --------------------------------------------------------------------------


async def build_registry(scenario: str) -> InMemoryProviderRegistry:
    registry = InMemoryProviderRegistry(_catalog())
    if scenario == "opus-degraded":
        registry.mark_unavailable("claude-3-opus")
    elif scenario != "all-available":
        raise ValueError(f"unknown scenario: {scenario!r}")
    return registry


async def run_benchmark(
    seed: str = "routing-bench-v1",
    tasks_per_class: int = 400,
    scenario: str = "all-available",
) -> dict[str, object]:
    """Route one shared corpus through every policy; score each against one
    shared, precomputed outcome table."""
    corpus = make_corpus(seed, tasks_per_class)
    registry = await build_registry(scenario)
    router = CostAwareRouter(registry)

    # Outcome table FIRST — policies are scored against it, never shaped by it
    # (except the oracle, whose definition is "chosen after outcomes").
    outcomes = await build_outcome_table(corpus, registry, seed)

    policies: list[RoutingPolicy] = [
        ShippedRouterPolicy(registry, router),
        ShippedRouterPolicy(registry, router, STATIC_CHEAP_BUDGET, name="static-cheap"),
        BudgetConditionedPolicy(registry, router),
        TierConditionedPolicy(registry),
        OraclePolicy(registry, outcomes),
    ]

    routed_by_policy: dict[str, list[tuple[TaskCase, str | None]]] = {}
    for policy in policies:
        routed_by_policy[policy.name] = await route_all(policy, corpus)

    models = await registry.list_models()
    metadata = {m.name: m for m in models}
    reports = [
        score_policy(
            policy.name,
            routed_by_policy[policy.name],
            metadata,
            outcomes,
            policy.route_failures,
        )
        for policy in policies
    ]
    by_name = {r.policy: r for r in reports}
    oracle = by_name["oracle"]

    # Stability: selection flip rate under bounded feature jitter. The oracle
    # is exempt: jitter legitimately changes what utility-maximizes.
    stability = {
        policy.name: round(await selection_flip_rate(policy, corpus, seed + "|jitter"), 4)
        for policy in policies
        if policy.name != "oracle"
    }

    # Leakage: outcome-blind policies must have zero violations; the oracle is
    # the positive control and is expected to move (reported, not counted as a
    # violation).
    leakage = {
        policy.name: await leakage_audit(policy, corpus, registry, seed)
        for policy in policies
        if policy.name != "oracle"
    }
    oracle_audit = await leakage_audit(OraclePolicy(registry, outcomes), corpus, registry, seed)

    baseline = by_name["shipped-router"]
    comparisons: dict[str, dict[str, float]] = {}
    for report in reports:
        if report.policy == "shipped-router":
            continue
        comparisons[report.policy] = {
            "delta_success_rate": round(report.success_rate - baseline.success_rate, 4),
            "delta_cost_per_task_cents": round(
                report.cost_cents_per_task - baseline.cost_cents_per_task, 6
            ),
            "delta_latency_p95_ms": round(report.latency_p95_ms - baseline.latency_p95_ms, 1),
            "delta_mean_utility": round(report.mean_utility - baseline.mean_utility, 4),
            "regret_vs_oracle": round(oracle.mean_utility - report.mean_utility, 4),
        }

    return {
        "benchmark": "task-conditioned-model-routing",
        "issue": "914",
        "epic": "900",
        "seam": {
            "router": "maistro.providers.router.CostAwareRouter (shipped, unmodified)",
            "registry": "maistro.providers.registry.InMemoryProviderRegistry",
            "cost": "maistro.providers.types.compute_cost_cents",
            "note": (
                "selection seam is production code; outcomes are a fixed "
                "deterministic simulator over (task, model) pairs because the "
                "repository records no per-task routing telemetry"
            ),
        },
        "config": {
            "seed": seed,
            "tasks_per_class": tasks_per_class,
            "corpus_size": len(corpus),
            "scenario": scenario,
            "task_classes": list(CLASS_NAMES),
            "utility_weights": {
                "success": "+1.0 / miss -0.25",
                "cost_cents": 0.05,
                "latency_ms": 0.0002,
            },
        },
        "policies": [asdict(r) for r in reports],
        "comparisons_vs_shipped": comparisons,
        "stability_flip_rate_under_jitter": stability,
        "leakage_violations": leakage,
        "leakage_positive_control_oracle_changes": oracle_audit,
    }


def _print_summary(report: dict[str, object]) -> None:
    policies = report["policies"]
    assert isinstance(policies, list)
    header = (
        f"{'policy':<20} {'success':>8} {'¢/task':>8} {'¢/succ':>8} "
        f"{'p50 ms':>8} {'p95 ms':>8} {'miss':>6} {'HHI':>6} {'utility':>8}"
    )
    print(header)
    print("-" * len(header))
    for p in policies:
        assert isinstance(p, dict)
        print(
            f"{p['policy']:<20} {p['success_rate']:>8.3f} {p['cost_cents_per_task']:>8.4f} "
            f"{p['cost_cents_per_success']:>8.4f} {p['latency_p50_ms']:>8.1f} "
            f"{p['latency_p95_ms']:>8.1f} {p['deadline_miss_rate']:>6.3f} "
            f"{p['model_hhi']:>6.3f} {p['mean_utility']:>8.4f}"
        )
    print(f"\nstability (flip rate under ±5% jitter): {report['stability_flip_rate_under_jitter']}")
    print(f"leakage violations (outcome-blind policies; must be 0): {report['leakage_violations']}")
    print(
        f"leakage positive control (oracle must move): "
        f"{report['leakage_positive_control_oracle_changes']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks-per-class", type=int, default=400)
    parser.add_argument("--seed", default="routing-bench-v1")
    parser.add_argument(
        "--scenario", choices=["all-available", "opus-degraded"], default="all-available"
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    report = asyncio.run(run_benchmark(args.seed, args.tasks_per_class, args.scenario))
    payload = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n")
    _print_summary(report)
    if args.output:
        print(f"\nwritten: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
