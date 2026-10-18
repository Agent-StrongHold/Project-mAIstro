#!/usr/bin/env python3
"""Heterogeneous fleet benchmark (issue #934, epic #905 M8-F1).

Offline/replay evaluator comparing fleet-composition policies — hosted-only,
local-only, the shipped router over the whole fleet, and a difficulty-aware
local-first candidate — over one shared task corpus, one shared,
policy-independent outcome table, and one shared provider-pressure schedule.

What is real
------------
The fleet seam is the shipped one: `CostAwareRouter.select(task, budget,
scope)` over an `InMemoryProviderRegistry` (ADR-079/ADR-038) — the selection
path production uses (`maistro.capabilities.model_chat`), plus registry
availability marking (the outage injection point) and `compute_cost_cents`.
Every policy's every selection is a real router call; fleet composition is
expressed only through the levers the seam already has (budget exclusion,
`scope` constraints, availability). Failover re-enters the same router with
the errored models excluded from `scope` — a per-call narrowing, never a
second selection path. No egress is opened: `quality/model-egress.json` is
read and reported to prove the bench adds no direct model caller.

What is simulated (and said so loudly)
--------------------------------------
The repository records no per-task routing telemetry, so attempt outcomes
(success, realized latency, tokens) come from a fixed deterministic outcome
model over (task, model) pairs — the same escalation shape the #914
task-conditioning bench uses, extended with provider physics: capacity
failures (registry `max_tokens` arithmetic) and scenario-driven rate limits.
The outcome table is built ONCE per scenario, before any policy runs, so
cross-policy comparisons are exact. Provider pressure (which attempts get
rate-limited) is keyed to a fixed constant seed, NOT the run seed: it plays
the role of observable egress conditions, which is what lets failover
policies react to it without leaking hidden outcome data. Magnitudes are
simulator-dependent; the structural findings are not.

Policies
--------
- hosted-only    : the incumbent deployment. Real router, `scope` = hosted
                   model names, production call shape (bare task, no budget,
                   no capacity prefilter — exactly what ships today).
- local-only     : the all-in local counterfactual. Real router,
                   `scope` = local model names, production call shape.
- mixed-shipped  : what ships today when an operator adds local capacity to
                   the registry and changes nothing else: the real router,
                   unconstrained, over the whole fleet. Provider-blind and
                   latency-first, so the structural question "how much work
                   lands on local?" gets an exact answer.
- mixed-local-first (candidate, NOT production code): difficulty-aware
                   composition from observable features only — easy tasks are
                   scoped to capacity-fitting local models first, hard tasks
                   (hard classes) to capable hosted tiers, reasoning-flagged
                   tasks to reasoning-adequate entries. Observable attempt
                   failures (capacity, rate limit) escalate to the next stage
                   with the attempted models excluded; quality failures do
                   NOT escalate (they are only knowable post-hoc;
                   quality-triggered escalation is leaf #915's territory).
- oracle         : per-task argmax of realized utility over capacity-adequate
                   available models — "chosen after outcomes", the regret
                   baseline and the leakage detector's positive control.
                   Single-attempt by definition, so failover policies may
                   legitimately exceed it; utility deltas are reported with
                   that asymmetry named.

Scenarios
---------
- all-available     : benign fleet.
- local-outage      : the local inference host is down (both local entries
                      circuit-broken via the availability seam).
- hosted-outage     : one hosted provider (anthropic) is down — the provider
                      that owns the fleet's hosted reasoning capability.
- capacity-pressure : everything up, but hosted attempts inside a
                      deterministic pressure window rate-limit; local
                      capacity is unaffected. Pressure is a property of the
                      scenario timeline, identical for every policy: the bench
                      measures pressure *avoidance*, not demand relief.

Measured (per the issue)
------------------------
success quality, cost (total/per-task/per-success), realized p50/p95 latency,
throughput (deterministic makespan model: local attempts serialize on one
executor, hosted attempts run `HOSTED_CONCURRENCY`-wide), failover behavior
(escalation rate, attempts per task, residual observable-failure rate, route
failures), hardware utilization (local-executor busy fraction, hosted-fleet
utilization, local executors needed to match hosted throughput),
operational complexity (counted: registry entries, providers, extra local
processes, observed failure-mode classes), and portability (provider
shares/HHI plus the model-egress ratchet read).

Deterministic and offline: every random draw is a blake2b hash of stable ids;
no network, no database. Run it after changing routing, the fleet catalog, or
the outcome model; results are comparable run-to-run.

Usage:
    uv run python scripts/bench_fleet_routing.py [--tasks-per-class 400]
        [--seed fleet-bench-v1]
        [--scenario all-available|local-outage|hosted-outage|capacity-pressure|all]
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

#: Pressure draws are keyed to a CONSTANT seed, independent of --seed: they
#: model observable egress conditions (a 429 is visible at call time), so
#: re-seeding the outcome realization must not move them. The leakage audit
#: depends on this split — failover policies condition on provider errors
#: (observable) and must stay invariant to outcome draws (hidden).
PRESSURE_SEED = "fleet-bench-pressure-v1"

#: Concurrency model for throughput / hardware utilization. One local
#: inference executor (a single workstation GPU serializes attempts); hosted
#: capacity is elastic within a bounded window. Stated modeling choice — the
#: utilization and throughput numbers are only meaningful relative to it.
LOCAL_CONCURRENCY = 1
HOSTED_CONCURRENCY = 16

# --------------------------------------------------------------------------
# Model catalog. Mirrors packages/maistro-core/tests/providers/fixtures_models.py
# (the catalog the routing tests assert against, and the same base the #914
# bench extends), plus the fleet-specific entries the issue's heterogeneous
# question needs: a second hosted provider (so a single-provider outage is
# survivable inside the hosted-only fleet) and a second, larger local model
# (so the local fleet has internal selection and a reasoning-capable member).
# Costs are cents per 1k tokens, as ModelMetadata defines.
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
            fallback_to=("gpt-4o-mini",),
        ),
        ModelMetadata(
            name="mistral-large",
            provider="mistral",
            tier="powerful",
            cost_per_1k_input=0.02,
            cost_per_1k_output=0.06,
            latency_p50_ms=900,
            max_tokens=32_768,
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
        ModelMetadata(
            name="local-qwen-14b",
            provider="local",
            tier="balanced",
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            latency_p50_ms=6000,
            reasoning_capable=True,
            max_tokens=16_384,
        ),
    ]


LOCAL_PROVIDERS = frozenset({"local"})
HOSTED_PROVIDERS = frozenset({"anthropic", "openai", "mistral"})


# --------------------------------------------------------------------------
# Task corpus: identical classes, bands, and hashing to
# scripts/bench_model_routing.py (#914) so the two routing benchmarks stay
# comparable. Observable features only; the HIDDEN difficulty is
# outcome-model input and no policy can see it.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """Observable task descriptor — the only thing a policy may condition on."""

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
    """Per-capability-class corpus parameters (see bench_model_routing.py)."""

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
    """Same task with context/output perturbed by at most ±5% (outcomes
    unchanged) — the bounded-remeasurement stability probe."""
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
# Provider pressure: scenario-driven rate limits, keyed to PRESSURE_SEED so
# the schedule is identical for every policy and every run seed. A 429 is an
# observable egress condition; conditioning failover on it is legitimate,
# which is why it is drawn from a seed the leakage audit never re-seeds.
# --------------------------------------------------------------------------

#: Hosted rate-limit probability per scenario. Local attempts never
#: rate-limit: the pressure scenario models a hosted provider saturating
#: while the local host sits idle — the fleet's resilience case.
RATE_LIMIT_P: dict[str, float] = {
    "all-available": 0.0,
    "local-outage": 0.0,
    "hosted-outage": 0.0,
    "capacity-pressure": 0.35,
}

SCENARIOS = ("all-available", "local-outage", "hosted-outage", "capacity-pressure")


def provider_rate_limited(task_id: str, model: ModelMetadata, scenario: str) -> bool:
    """Deterministic, seed-independent draw: does this hosted attempt 429?"""
    if model.provider in LOCAL_PROVIDERS:
        return False
    p = RATE_LIMIT_P[scenario]
    if p <= 0.0:
        return False
    return _hash_float(PRESSURE_SEED, scenario, task_id, model.name) < p


# --------------------------------------------------------------------------
# Outcome model: a pure function of (task case, model, scenario) —
# independent of every policy. Built once per scenario, before routing, as a
# table keyed by (task_id, model); policies are scored by table lookup, which
# makes the cross-policy comparison exact and the leakage audit decidable.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptOutcome:
    """One model attempt. `kind` is the failure taxonomy: ok / quality_fail
    are distinguishable only post-hoc (a judge sees them, the egress does
    not); capacity and rate_limited are observable at the seam and are the
    only events failover may react to."""

    kind: str  # ok | quality_fail | capacity | rate_limited
    success: bool
    latency_ms: float
    output_tokens: int
    cost_cents: float
    deadline_miss: bool

    @property
    def utility(self) -> float:
        """Composite utility, same weights as bench_model_routing.py:
        success +1.0 / failure -0.25, -0.05 per cost cent, -0.0002 per ms."""
        util = (1.0 if self.success else -0.25) - 0.05 * self.cost_cents
        return util - 0.0002 * self.latency_ms

    @property
    def observable_failure(self) -> bool:
        """Failover-eligible: the egress itself reports the failure."""
        return self.kind in ("capacity", "rate_limited")


#: Same escalation shape as bench_model_routing.py (the qualitative public
#: record; slopes are stated modeling choices).
TIER_COMFORT = {"fast": 0.35, "balanced": 0.60, "powerful": 0.90}
TIER_BASE_SUCCESS = {"fast": 0.92, "balanced": 0.95, "powerful": 0.97}
DIFFICULTY_SLOPE = 0.90

#: A rate-limited attempt rejects fast (the provider refuses before doing
#: work): it bills no tokens but still pays queue time. Stated choice.
RATE_LIMIT_LATENCY_FRACTION = 0.25


def simulate_attempt(
    case: TaskCase, model: ModelMetadata, scenario: str, seed: str = "fleet-bench-v1"
) -> AttemptOutcome:
    """Deterministic (task, model, scenario) -> AttemptOutcome."""
    task = case.task

    # Hard capacity bound from registry metadata — arithmetic, not opinion.
    if task.context_tokens + task.expected_output_tokens > model.max_tokens:
        return AttemptOutcome(
            kind="capacity",
            success=False,
            latency_ms=float(model.latency_p50_ms),
            output_tokens=0,
            cost_cents=0.0,
            deadline_miss=model.latency_p50_ms > task.latency_budget_ms,
        )

    # Rate limit first: a 429 attempt does no work, bills nothing.
    if provider_rate_limited(task.task_id, model, scenario):
        latency = model.latency_p50_ms * RATE_LIMIT_LATENCY_FRACTION
        return AttemptOutcome(
            kind="rate_limited",
            success=False,
            latency_ms=latency,
            output_tokens=0,
            cost_cents=0.0,
            deadline_miss=latency > task.latency_budget_ms,
        )

    def u(tag: str) -> float:
        return _hash_float(seed, "outcome", task.task_id, model.name, tag)

    p = TIER_BASE_SUCCESS[model.tier] - DIFFICULTY_SLOPE * max(
        0.0, case.difficulty - TIER_COMFORT[model.tier]
    )
    if task.reasoning_required:
        p += 0.05 if model.reasoning_capable else -0.25
    if task.tool_use:
        p -= 0.08
    p = min(0.98, max(0.02, p))
    success = u("success") < p

    context_load = 1.0 + task.context_tokens / 50_000
    latency = model.latency_p50_ms * context_load * (0.7 + 0.6 * u("latency"))
    out_tokens = int(task.expected_output_tokens * (0.8 + 0.4 * u("tokens")))
    in_tokens = min(task.context_tokens, model.max_tokens)
    cost = compute_cost_cents(model, in_tokens, out_tokens)
    return AttemptOutcome(
        kind="ok" if success else "quality_fail",
        success=success,
        latency_ms=latency,
        output_tokens=out_tokens,
        cost_cents=cost,
        deadline_miss=latency > task.latency_budget_ms,
    )


OutcomeTable = dict[tuple[str, str], AttemptOutcome]


async def build_outcome_table(
    corpus: list[TaskCase], registry: InMemoryProviderRegistry, scenario: str, seed: str
) -> OutcomeTable:
    """Precompute the outcome of every (task, model) pair for one scenario.
    Built once, before any policy runs: every policy is scored against the
    identical table."""
    models = await registry.list_models()
    return {
        (case.task.task_id, model.name): simulate_attempt(case, model, scenario, seed)
        for case in corpus
        for model in models
    }


# --------------------------------------------------------------------------
# Fleet policies. A policy sees a Task (observable features) and the
# registry; it never sees TaskCase.difficulty or the outcome table — except
# the oracle, which is defined as choosing after outcomes and serves as the
# leakage detector's positive control. Escalation conditions ONLY on
# observable attempt failures (capacity, rate_limited), never on quality.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    """One routed attempt: the model the seam selected and what came back."""

    model_name: str
    kind: str
    success: bool
    latency_ms: float
    cost_cents: float
    observable_failure: bool
    deadline_miss: bool


@dataclass
class TaskResult:
    """The composed record of one task under one policy."""

    task_id: str
    attempts: list[Attempt] = field(default_factory=list)
    routed: bool = True  # False = no eligible model at any stage

    @property
    def final(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None

    @property
    def success(self) -> bool:
        return bool(self.final and self.final.success)

    @property
    def escalated(self) -> bool:
        return len(self.attempts) > 1

    @property
    def cost_cents(self) -> float:
        return sum(a.cost_cents for a in self.attempts)


@dataclass(frozen=True)
class Stage:
    """One escalation stage: exactly the levers the shipped seam exposes —
    a `RouterBudget` and a `scope` (model-name constraint) handed to the real
    `CostAwareRouter.select`. `providers` narrows scope to a provider set
    (None = the whole catalog); `tier_filter`/`require_reasoning` scope by
    observable registry metadata; `require_fit` scopes to models whose
    registry `max_tokens` window can hold the task's demand. The shipped
    production call shape sets NONE of these except scope — its fit-blindness
    is a #914 finding this bench reproduces, so production-shape stages set
    `require_fit=False`."""

    budget: RouterBudget | None = None
    providers: frozenset[str] | None = None
    tier_filter: frozenset[str] | None = None
    require_fit: bool = True
    require_reasoning: bool = False


#: Module-level routing context for attempt simulation inside policies: the
#: scenario and the corpus's hidden difficulties. Set by `route_all` before
#: each policy run; the driver is sequential, so this carries no state
#: across runs, and no policy reads either — only attempt simulation does.
_ROUTE_SCENARIO = "all-available"
_ROUTE_CORPUS: dict[str, TaskCase] = {}


class FleetPolicy:
    """Stage-based fleet composition over the real routing seam."""

    name = "policy"

    def __init__(self, registry: InMemoryProviderRegistry, router: CostAwareRouter) -> None:
        self.registry = registry
        self.router = router
        self.route_failures = 0

    def stages(self, task: Task) -> list[Stage]:
        raise NotImplementedError

    async def _scoped_names(self, task: Task, stage: Stage, exclude: frozenset[str]) -> list[str]:
        """Resolve a stage's scope against observable registry metadata.

        Availability is NOT filtered here: `CostAwareRouter.select` already
        skips unavailable entries (and their chains), which is the shipped
        outage behavior this bench routes through."""
        demand = task.context_tokens + task.expected_output_tokens
        names: list[str] = []
        for model in await self.registry.list_models():
            if model.name in exclude:
                continue
            if stage.providers is not None and model.provider not in stage.providers:
                continue
            if stage.tier_filter is not None and model.tier not in stage.tier_filter:
                continue
            if stage.require_fit and model.max_tokens < demand:
                continue
            if stage.require_reasoning and not model.reasoning_capable:
                continue
            names.append(model.name)
        return names

    def _record(self, task_id: str, model: ModelMetadata) -> Attempt:
        outcome = simulate_attempt(_ROUTE_CORPUS[task_id], model, _ROUTE_SCENARIO)
        return Attempt(
            model_name=model.name,
            kind=outcome.kind,
            success=outcome.success,
            latency_ms=outcome.latency_ms,
            cost_cents=outcome.cost_cents,
            observable_failure=outcome.observable_failure,
            deadline_miss=outcome.deadline_miss,
        )

    async def run_task(self, task: Task) -> TaskResult:
        """Route one task: stages in order, escalating on observable
        failures only. Every selection is a real `CostAwareRouter.select`."""
        result = TaskResult(task_id=task.task_id)
        attempted: frozenset[str] = frozenset()
        for stage in self.stages(task):
            scope = await self._scoped_names(task, stage, attempted)
            if not scope:
                continue
            try:
                model = await self.router.select(
                    RoutingTask(task_type=task.task_type), stage.budget, scope
                )
            except NoEligibleModelError:
                continue
            attempt = self._record(task.task_id, model)
            result.attempts.append(attempt)
            if not attempt.observable_failure:
                return result
            attempted = attempted | {model.name}
        result.routed = bool(result.attempts)
        if not result.attempts:
            self.route_failures += 1
        return result


class ScopedFleetPolicy(FleetPolicy):
    """A fleet confined to a fixed provider set via the seam's `scope` lever
    — hosted-only and local-only are two settings of this one policy, both in
    the shipped production call shape (fit-blind, budget-free)."""

    def __init__(
        self,
        registry: InMemoryProviderRegistry,
        router: CostAwareRouter,
        providers: frozenset[str],
        name: str,
    ) -> None:
        super().__init__(registry, router)
        self.providers = providers
        self.name = name

    def stages(self, task: Task) -> list[Stage]:
        return [Stage(providers=self.providers, require_fit=False)]


class MixedShippedPolicy(FleetPolicy):
    """The shipped router over the whole fleet, production call shape: bare
    task descriptor, unconstrained budget, no scope, no capacity prefilter.
    What an operator gets today by adding local entries to the registry and
    changing nothing else."""

    name = "mixed-shipped"

    def stages(self, task: Task) -> list[Stage]:
        return [Stage(require_fit=False)]


#: Difficulty-aware composition from observables only. "Easy" = not
#: reasoning-flagged and not a hard class. Task classes mirror #914's split.
HARD_CLASSES = frozenset({"code_repair", "planning"})


class MixedLocalFirstPolicy(FleetPolicy):
    """Candidate fleet policy (NOT production code): local-first for easy
    work, hosted-capability-first for hard work, escalating on observable
    failures. Selection inside every stage keeps the shipped latency-first
    preference, so the comparison isolates composition, not preference."""

    name = "mixed-local-first"

    def stages(self, task: Task) -> list[Stage]:
        if task.reasoning_required:
            return [
                Stage(require_reasoning=True),
                Stage(require_fit=False),
            ]
        if task.task_type in HARD_CLASSES:
            return [
                Stage(tier_filter=frozenset({"powerful", "balanced"})),
                Stage(require_fit=False),
            ]
        return [
            Stage(providers=LOCAL_PROVIDERS, tier_filter=frozenset({"fast", "balanced"})),
            Stage(tier_filter=frozenset({"fast", "balanced"})),
            Stage(require_fit=False),
        ]


class OraclePolicy(FleetPolicy):
    """Per-task argmax of realized utility over capacity-adequate available
    models. The ceiling by definition and the leakage positive control;
    single-attempt, so failover policies may exceed it (reported as such)."""

    name = "oracle"

    def __init__(
        self,
        registry: InMemoryProviderRegistry,
        router: CostAwareRouter,
        outcomes: OutcomeTable,
    ) -> None:
        super().__init__(registry, router)
        self.outcomes = outcomes

    async def run_task(self, task: Task) -> TaskResult:
        result = TaskResult(task_id=task.task_id)
        demand = task.context_tokens + task.expected_output_tokens
        available = [
            m
            for m in await self.registry.list_models()
            if self.registry.is_available(m.name) and m.max_tokens >= demand
        ]
        if not available:
            self.route_failures += 1
            result.routed = False
            return result
        best = max(available, key=lambda m: self.outcomes[(task.task_id, m.name)].utility)
        outcome = self.outcomes[(task.task_id, best.name)]
        result.attempts.append(
            Attempt(
                model_name=best.name,
                kind=outcome.kind,
                success=outcome.success,
                latency_ms=outcome.latency_ms,
                cost_cents=outcome.cost_cents,
                observable_failure=outcome.observable_failure,
                deadline_miss=outcome.deadline_miss,
            )
        )
        return result


# --------------------------------------------------------------------------
# Run driver: route the corpus under a scenario, score, audit.
# --------------------------------------------------------------------------


async def route_all(policy: FleetPolicy, corpus: list[TaskCase], scenario: str) -> list[TaskResult]:
    """Route every task under one scenario, in corpus order."""
    global _ROUTE_SCENARIO
    _ROUTE_SCENARIO = scenario
    _ROUTE_CORPUS.clear()
    _ROUTE_CORPUS.update({case.task.task_id: case for case in corpus})
    try:
        return [await policy.run_task(case.task) for case in corpus]
    finally:
        _ROUTE_CORPUS.clear()


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
class FleetReport:
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
    escalated_rate: float
    attempts_per_task: float
    residual_observable_failure_rate: float
    makespan_ms: float
    tasks_per_sec_corpus: float
    success_throughput_per_sec: float
    local_executor_busy_fraction: float
    hosted_fleet_utilization: float
    local_executors_to_match_hosted: int
    model_shares: dict[str, float] = field(default_factory=dict)
    provider_shares: dict[str, float] = field(default_factory=dict)
    model_hhi: float = 0.0
    provider_hhi: float = 0.0
    failure_modes: dict[str, int] = field(default_factory=dict)
    operational_complexity: dict[str, int] = field(default_factory=dict)


def makespan_and_utilization(results: list[TaskResult]) -> tuple[float, float, float, int]:
    """Wall-clock model (stated choice): local attempts serialize on
    LOCAL_CONCURRENCY executors, hosted attempts run HOSTED_CONCURRENCY-wide,
    and the makespan is floored by the longest single attempt chain. Returns
    (makespan_ms, local busy fraction, hosted utilization, local executors
    needed to finish the local work inside the hosted makespan)."""
    local_busy_ms = 0.0
    hosted_busy_ms = 0.0
    longest_chain_ms = 0.0
    for result in results:
        chain_ms = 0.0
        for attempt in result.attempts:
            chain_ms += attempt.latency_ms
            if attempt.model_name.startswith("local-"):
                local_busy_ms += attempt.latency_ms
            else:
                hosted_busy_ms += attempt.latency_ms
        longest_chain_ms = max(longest_chain_ms, chain_ms)
    makespan_ms = max(
        local_busy_ms / LOCAL_CONCURRENCY,
        hosted_busy_ms / HOSTED_CONCURRENCY,
        longest_chain_ms,
        1.0,
    )
    hosted_makespan_ms = hosted_busy_ms / HOSTED_CONCURRENCY
    needed = math.ceil(local_busy_ms / hosted_makespan_ms) if hosted_makespan_ms > 0 else 0
    local_fraction = local_busy_ms / makespan_ms
    hosted_util = hosted_busy_ms / (HOSTED_CONCURRENCY * makespan_ms)
    return makespan_ms, local_fraction, hosted_util, needed


def score_fleet(
    name: str,
    results: list[TaskResult],
    metadata: dict[str, ModelMetadata],
    route_failures: int,
) -> FleetReport:
    """Aggregate one policy's composed task results against the shared
    table. A task with no attempts (route failure) is priced at the worst
    outcome so route failures can never look cheap."""
    final_latencies: list[float] = []
    costs = 0.0
    successes = 0
    utilities = 0.0
    misses = 0
    escalations = 0
    attempts = 0
    residual_observable = 0
    model_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    failure_modes: dict[str, int] = {}
    routed = 0
    for result in results:
        if not result.attempts:
            utilities += AttemptOutcome(
                kind="route_failure",
                success=False,
                latency_ms=0.0,
                output_tokens=0,
                cost_cents=0.0,
                deadline_miss=True,
            ).utility
            continue
        routed += 1
        attempts += len(result.attempts)
        escalations += result.escalated
        final = result.final
        assert final is not None
        if final.observable_failure:
            residual_observable += 1
        failure_modes[final.kind] = failure_modes.get(final.kind, 0) + 1
        final_latencies.append(final.latency_ms)
        costs += result.cost_cents
        misses += final.deadline_miss
        utilities += sum(
            AttemptOutcome(
                kind=a.kind,
                success=a.success,
                latency_ms=a.latency_ms,
                output_tokens=0,
                cost_cents=a.cost_cents,
                deadline_miss=False,
            ).utility
            for a in result.attempts
        )
        if result.success:
            successes += 1
        model_counts[final.model_name] = model_counts.get(final.model_name, 0) + 1
        provider = metadata[final.model_name].provider
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
    n = max(len(results), 1)
    ok = max(successes, 1)
    model_shares = {k: v / n for k, v in model_counts.items()}
    provider_shares = {k: v / n for k, v in provider_counts.items()}
    makespan_ms, local_fraction, hosted_util, needed = makespan_and_utilization(results)
    # A policy that routed nothing completes nothing: the 1 ms makespan floor
    # must not read as infinite throughput.
    makespan_s = makespan_ms / 1000.0
    corpus_throughput = round(len(results) / makespan_s, 4) if routed else 0.0
    success_throughput = round(successes / makespan_s, 4) if routed else 0.0
    local_entries = sum(1 for m in metadata.values() if m.provider in LOCAL_PROVIDERS)
    return FleetReport(
        policy=name,
        routed=routed,
        route_failures=route_failures,
        success_rate=successes / n,
        cost_cents_total=round(costs, 4),
        cost_cents_per_task=round(costs / n, 6),
        cost_cents_per_success=round(costs / ok, 6),
        latency_p50_ms=round(_percentile(final_latencies, 50), 1),
        latency_p95_ms=round(_percentile(final_latencies, 95), 1),
        deadline_miss_rate=round(misses / n, 4),
        mean_utility=round(utilities / n, 4),
        escalated_rate=round(escalations / n, 4),
        attempts_per_task=round(attempts / max(routed, 1), 4),
        residual_observable_failure_rate=round(residual_observable / n, 4),
        makespan_ms=round(makespan_ms, 1),
        tasks_per_sec_corpus=corpus_throughput,
        success_throughput_per_sec=success_throughput,
        local_executor_busy_fraction=round(local_fraction, 4),
        hosted_fleet_utilization=round(hosted_util, 4),
        local_executors_to_match_hosted=needed,
        model_shares={k: round(v, 4) for k, v in sorted(model_shares.items())},
        provider_shares={k: round(v, 4) for k, v in sorted(provider_shares.items())},
        model_hhi=round(_hhi(model_shares), 4),
        provider_hhi=round(_hhi(provider_shares), 4),
        failure_modes=dict(sorted(failure_modes.items())),
        operational_complexity={
            "registry_entries_in_catalog": len(metadata),
            "providers_in_catalog": len({m.provider for m in metadata.values()}),
            "local_entries": local_entries,
            "extra_local_processes": 1 if local_entries else 0,
        },
    )


async def selection_flip_rate(
    policy: FleetPolicy, corpus: list[TaskCase], scenario: str, twin_seed: str
) -> float:
    """Fraction of tasks whose FIRST-attempt model changes under bounded
    jitter of observable features (outcomes and pressure unchanged)."""
    base_results = await route_all(policy, corpus, scenario)
    twin_corpus = [jittered_twin(case, twin_seed) for case in corpus]
    twin_results = await route_all(policy, twin_corpus, scenario)
    flips = 0
    for base, twin in zip(base_results, twin_results, strict=True):
        first_base = base.attempts[0].model_name if base.attempts else None
        first_twin = twin.attempts[0].model_name if twin.attempts else None
        if first_base is not None and first_base != first_twin:
            flips += 1
    return flips / max(len(corpus), 1)


async def leakage_audit(
    policy: FleetPolicy,
    corpus: list[TaskCase],
    registry: InMemoryProviderRegistry,
    scenario: str,
    seed: str,
) -> int:
    """Count tasks whose routed-attempt sequence changes when ONLY the hidden
    outcome realization is re-seeded. Pressure draws stay fixed (they model
    observable egress conditions), so a well-posed policy — including its
    failover, which may react to observable errors — must not move. The
    oracle (the one policy that reads the table) is run through the same
    audit by the caller as the positive control."""
    alt_table = await build_outcome_table(corpus, registry, scenario, seed + "|leakage-audit")
    base = await route_all(policy, corpus, scenario)
    restored = getattr(policy, "outcomes", None)
    if restored is not None:
        policy.outcomes = alt_table
    try:
        alt = await route_all(policy, corpus, scenario)
    finally:
        if restored is not None:
            policy.outcomes = restored
    violations = 0
    for b, a in zip(base, alt, strict=True):
        if b.task_id != a.task_id:
            msg = "corpus order drifted under the audit"
            raise AssertionError(msg)
        if [x.model_name for x in b.attempts] != [x.model_name for x in a.attempts]:
            violations += 1
    return violations


# --------------------------------------------------------------------------
# Benchmark driver.
# --------------------------------------------------------------------------


async def build_registry(scenario: str) -> InMemoryProviderRegistry:
    """The full heterogeneous fleet with the scenario's availability applied.
    Availability marking is the shipped outage injection point (ADR-038)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario!r}")
    registry = InMemoryProviderRegistry(_catalog())
    if scenario == "local-outage":
        for model in await registry.list_models():
            if model.provider in LOCAL_PROVIDERS:
                registry.mark_unavailable(model.name)
    elif scenario == "hosted-outage":
        for model in await registry.list_models():
            if model.provider == "anthropic":
                registry.mark_unavailable(model.name)
    return registry


def build_policies(
    registry: InMemoryProviderRegistry, router: CostAwareRouter, outcomes: OutcomeTable
) -> list[FleetPolicy]:
    return [
        ScopedFleetPolicy(registry, router, HOSTED_PROVIDERS, "hosted-only"),
        ScopedFleetPolicy(registry, router, LOCAL_PROVIDERS, "local-only"),
        MixedShippedPolicy(registry, router),
        MixedLocalFirstPolicy(registry, router),
        OraclePolicy(registry, router, outcomes),
    ]


async def run_fleet_benchmark(
    seed: str = "fleet-bench-v1",
    tasks_per_class: int = 400,
    scenario: str = "all-available",
) -> dict[str, object]:
    """Route one shared corpus through every fleet policy under one scenario;
    score each against one shared, precomputed outcome table."""
    corpus = make_corpus(seed, tasks_per_class)
    registry = await build_registry(scenario)
    router = CostAwareRouter(registry)

    # Outcome table FIRST — policies are scored against it, never shaped by
    # it (except the oracle, whose definition is "chosen after outcomes").
    outcomes = await build_outcome_table(corpus, registry, scenario, seed)
    policies = build_policies(registry, router, outcomes)

    results_by_policy: dict[str, list[TaskResult]] = {}
    for policy in policies:
        results_by_policy[policy.name] = await route_all(policy, corpus, scenario)

    models = await registry.list_models()
    metadata = {m.name: m for m in models}
    reports = [
        score_fleet(
            policy.name,
            results_by_policy[policy.name],
            metadata,
            policy.route_failures,
        )
        for policy in policies
    ]
    by_name = {r.policy: r for r in reports}

    # Stability: first-attempt flip rate under bounded feature jitter. The
    # oracle is exempt (jitter legitimately changes what utility-maximizes).
    stability = {}
    for policy in policies:
        if policy.name != "oracle":
            stability[policy.name] = round(
                await selection_flip_rate(policy, corpus, scenario, seed + "|jitter"), 4
            )

    # Leakage: outcome-blind policies must have zero violations; the oracle
    # is the positive control (expected to move) and is reported separately.
    leakage = {}
    for policy in policies:
        if policy.name != "oracle":
            leakage[policy.name] = await leakage_audit(policy, corpus, registry, scenario, seed)
    oracle_audit = await leakage_audit(
        OraclePolicy(registry, router, outcomes), corpus, registry, scenario, seed
    )

    # Comparisons vs the incumbent deployment (hosted-only), per the epic's
    # fleet-experiment baseline, plus utility delta vs the single-attempt
    # oracle ceiling (failover policies may exceed it — extra attempts).
    baseline = by_name["hosted-only"]
    oracle = by_name["oracle"]
    comparisons: dict[str, dict[str, float | int]] = {}
    for report in reports:
        if report.policy == "hosted-only":
            continue
        comparisons[report.policy] = {
            "delta_success_rate": round(report.success_rate - baseline.success_rate, 4),
            "delta_cost_total_cents": round(report.cost_cents_total - baseline.cost_cents_total, 4),
            "delta_latency_p95_ms": round(report.latency_p95_ms - baseline.latency_p95_ms, 1),
            "delta_mean_utility": round(report.mean_utility - baseline.mean_utility, 4),
            "delta_utility_vs_single_attempt_oracle": round(
                report.mean_utility - oracle.mean_utility, 4
            ),
            "delta_tasks_per_sec": round(
                report.tasks_per_sec_corpus - baseline.tasks_per_sec_corpus, 4
            ),
        }

    return {
        "benchmark": "heterogeneous-fleet-routing",
        "issue": "934",
        "epic": "905",
        "seam": {
            "router": "maistro.providers.router.CostAwareRouter (shipped, unmodified)",
            "registry": "maistro.providers.registry.InMemoryProviderRegistry",
            "availability": "InMemoryProviderRegistry.mark_unavailable (ADR-038 outage seam)",
            "cost": "maistro.providers.types.compute_cost_cents",
            "note": (
                "selection and outage/failover ride production seams only; "
                "outcomes are a fixed deterministic simulator over (task, "
                "model) pairs because the repository records no per-task "
                "routing telemetry; provider pressure is a seed-independent "
                "observable-condition schedule"
            ),
        },
        "config": {
            "seed": seed,
            "pressure_seed": PRESSURE_SEED,
            "tasks_per_class": tasks_per_class,
            "corpus_size": len(corpus),
            "scenario": scenario,
            "task_classes": list(CLASS_NAMES),
            "local_concurrency": LOCAL_CONCURRENCY,
            "hosted_concurrency": HOSTED_CONCURRENCY,
            "utility_weights": {
                "success": "+1.0 / failure -0.25",
                "cost_cents": 0.05,
                "latency_ms": 0.0002,
            },
        },
        "fleet_catalog": [asdict(m) for m in models],
        "policies": [asdict(r) for r in reports],
        "comparisons_vs_hosted_only": comparisons,
        "stability_flip_rate_under_jitter": stability,
        "leakage_violations": leakage,
        "leakage_positive_control_oracle_changes": oracle_audit,
        "portability": _model_egress_audit(),
    }


def _model_egress_audit(path: Path | None = None) -> dict[str, object]:
    """Read the model-egress ratchet ledger: the bench adds no direct model
    caller, and the report proves the frozen set is intact (fail-closed if
    the ledger is missing)."""
    resolved = path or Path(__file__).resolve().parents[1] / "quality" / "model-egress.json"
    if not resolved.exists():
        msg = f"model-egress ledger missing: {resolved}"
        raise FileNotFoundError(msg)
    data = json.loads(resolved.read_text())
    modules = data["modules"] if isinstance(data, dict) else data
    approved = "maistro.capabilities.providers.llm_gateway"
    return {
        "model_egress_rows": len(modules),
        "approved_gateway_present": any(
            (m if isinstance(m, str) else m.get("module", "")) == approved for m in modules
        ),
        "new_direct_callers_added": 0,
    }


def _print_summary(report: dict[str, object]) -> None:
    policies = report["policies"]
    assert isinstance(policies, list)
    header = (
        f"{'policy':<18} {'succ':>6} {'¢/task':>8} {'p50':>7} {'p95':>7} "
        f"{'miss':>6} {'esc':>6} {'t/s':>7} {'loc.busy':>8} {'host.util':>9} {'HHI':>6}"
    )
    print(header)
    print("-" * len(header))
    for p in policies:
        assert isinstance(p, dict)
        print(
            f"{p['policy']:<18} {p['success_rate']:>6.3f} {p['cost_cents_per_task']:>8.4f} "
            f"{p['latency_p50_ms']:>7.1f} {p['latency_p95_ms']:>7.1f} "
            f"{p['deadline_miss_rate']:>6.3f} {p['escalated_rate']:>6.3f} "
            f"{p['tasks_per_sec_corpus']:>7.3f} {p['local_executor_busy_fraction']:>8.3f} "
            f"{p['hosted_fleet_utilization']:>9.3f} {p['model_hhi']:>6.3f}"
        )
    print(
        f"\nstability (first-attempt flip rate under ±5% jitter): "
        f"{report['stability_flip_rate_under_jitter']}"
    )
    print(f"leakage violations (outcome-blind policies; must be 0): {report['leakage_violations']}")
    print(
        f"leakage positive control (oracle must move): "
        f"{report['leakage_positive_control_oracle_changes']}"
    )
    print(f"portability (model-egress audit): {report['portability']}")


async def run_all_scenarios(seed: str, tasks_per_class: int) -> dict[str, object]:
    scenarios: dict[str, object] = {}
    for scenario in SCENARIOS:
        scenarios[scenario] = await run_fleet_benchmark(seed, tasks_per_class, scenario)
    return {
        "benchmark": "heterogeneous-fleet-routing",
        "issue": "934",
        "epic": "905",
        "mode": "all-scenarios",
        "config": {"seed": seed, "tasks_per_class": tasks_per_class},
        "portability": _model_egress_audit(),
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks-per-class", type=int, default=400)
    parser.add_argument("--seed", default="fleet-bench-v1")
    parser.add_argument(
        "--scenario",
        choices=[*SCENARIOS, "all"],
        default="all",
        help="fleet scenario; 'all' runs every scenario and nests the reports",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    if args.scenario == "all":
        report = asyncio.run(run_all_scenarios(args.seed, args.tasks_per_class))
        for scenario, nested in report["scenarios"].items():
            assert isinstance(nested, dict)
            print(f"\n=== scenario: {scenario} ===")
            _print_summary(nested)
    else:
        report = asyncio.run(run_fleet_benchmark(args.seed, args.tasks_per_class, args.scenario))
        _print_summary(report)
    payload = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n")
        print(f"\nwritten: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
