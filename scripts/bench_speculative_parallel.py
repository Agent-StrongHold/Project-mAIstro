#!/usr/bin/env python3
"""Speculative parallel model-call benchmark (issue #917, epic #900 M8-B4).

Compares four candidate-delivery strategies over the one governed model seam
(``ModelChatEgress``: Binding -> Invocation -> approved gateway Provider),
holding the workload fixed so every strategy is judged on identical physical
outcome schedules (common random numbers keyed by task and model):

* ``serial-fallback``   -- canonical baseline: the cost-aware router's
  low-latency-first fallback chain (ADR-079) tried one call at a time,
  escalating to the next candidate when the answer is not acceptable;
* ``single-strong``     -- always pin the strongest model, once;
* ``parallel-early-stop`` -- launch every candidate at once, deliver the first
  acceptable completion, cancel the rest;
* ``parallel-verifier`` -- launch every candidate, wait for all, let an
  independent noisy verifier rank the acceptable answers and select.

Every candidate call is its own governed Invocation with its own effect key:
duplicates are measured, never hidden. Provider physics (latency, transient
failure, answer quality) come from a deterministic offline simulation wired in
as the gateway transport; strategy decisions are taken on the simulated clock,
while each physical call really crosses the governed boundary in-process --
cancelled candidates surface as ``UNKNOWN`` Invocations, exactly as they would
in production. The numbers therefore compare candidate *policy* over a fixed
workload; they are not production-traffic measurements.

Usage:
    uv run python scripts/bench_speculative_parallel.py [--tasks 120]
        [--seed 917] [--scale 0.01] [--output results.json]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "maistro-core" / "src"))

import httpx

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.model_chat import (
    MODEL_CHAT_CAPABILITY,
    ModelCallResult,
    ModelChatEgress,
    ModelChatRequest,
)
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    GatewayEndpoint,
)
from maistro.credentials.types import CredentialRecord
from maistro.http import set_test_transport
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata

WORKSPACE_ID = "bench-speculative"
PROJECT_ID = "bench"
ENDPOINT = GatewayEndpoint(base_url="http://simulated-gateway")
#: One task in every ``OUTAGE_PERIOD`` loses one provider for the whole task:
#: every call to that provider fails together (correlated failure).
OUTAGE_PERIOD = 7
#: Independent per-call transient failure rate, on top of outage episodes.
TRANSIENT_FAILURE_RATE = 0.02
#: Verifier noise half-width: noisy score = true score +/- VERIFIER_NOISE / 2.
VERIFIER_NOISE = 0.2
#: Drawn latency is in ``[1 - LATENCY_JITTER, 1 + LATENCY_JITTER] x base``.
LATENCY_JITTER = 0.4
#: Cheapest/fastest candidate; the router fallback chain starts here.
CHAIN_HEAD = "quick-8b"
#: Reporting order of the compared strategies.
STRATEGY_ORDER = ("serial-fallback", "single-strong", "parallel-early-stop", "parallel-verifier")

DEFAULT_SEED = 917
DEFAULT_TASKS = 120
#: real sleep seconds = simulated model milliseconds / 1000 * SCALE.
DEFAULT_SCALE = 0.01


@dataclass(frozen=True)
class ModelSpec:
    """One simulated candidate: physics plus registry metadata in one place."""

    name: str
    provider: str
    latency_ms: int
    cost_per_1k_input: float
    cost_per_1k_output: float
    input_units: int
    output_units: int
    pass_rate: float
    quality_mean: float

    def metadata(self, *, fallback_to: tuple[str, ...] = ()) -> ModelMetadata:
        return ModelMetadata(
            name=self.name,
            provider=self.provider,
            cost_per_1k_input=self.cost_per_1k_input,
            cost_per_1k_output=self.cost_per_1k_output,
            latency_p50_ms=self.latency_ms,
            fallback_to=fallback_to,
        )


DIVERSE_CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        name="quick-8b",
        provider="alpha",
        latency_ms=900,
        cost_per_1k_input=0.15,
        cost_per_1k_output=0.60,
        input_units=900,
        output_units=350,
        pass_rate=0.78,
        quality_mean=0.72,
    ),
    ModelSpec(
        name="balanced-70b",
        provider="beta",
        latency_ms=2400,
        cost_per_1k_input=0.60,
        cost_per_1k_output=1.20,
        input_units=900,
        output_units=420,
        pass_rate=0.88,
        quality_mean=0.82,
    ),
    ModelSpec(
        name="strong-405b",
        provider="gamma",
        latency_ms=5200,
        cost_per_1k_input=2.00,
        cost_per_1k_output=4.00,
        input_units=950,
        output_units=500,
        pass_rate=0.96,
        quality_mean=0.93,
    ),
)


def catalog_for(topology: str) -> tuple[ModelSpec, ...]:
    """``diverse`` keeps one provider per model; ``same`` collapses them all.

    The ``same`` topology is the control for the provider-diversity question:
    identical physics, but every correlated outage now hits every candidate.
    """
    if topology == "diverse":
        return DIVERSE_CATALOG
    if topology == "same":
        return tuple(
            ModelSpec(
                name=spec.name,
                provider=DIVERSE_CATALOG[0].provider,
                latency_ms=spec.latency_ms,
                cost_per_1k_input=spec.cost_per_1k_input,
                cost_per_1k_output=spec.cost_per_1k_output,
                input_units=spec.input_units,
                output_units=spec.output_units,
                pass_rate=spec.pass_rate,
                quality_mean=spec.quality_mean,
            )
            for spec in DIVERSE_CATALOG
        )
    raise ValueError(f"unknown topology {topology!r}: expected 'diverse' or 'same'")


def build_registry(specs: tuple[ModelSpec, ...]) -> InMemoryProviderRegistry:
    """Registry wiring the canonical ADR-079 fallback chain: fast -> strong."""
    chain = [spec.name for spec in specs]
    models = [spec.metadata(fallback_to=tuple(chain[i + 1 :])) for i, spec in enumerate(specs)]
    return InMemoryProviderRegistry(models=models)


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _uniform(seed: int, *parts: object) -> float:
    digest = hashlib.blake2b(
        ":".join(str(part) for part in (seed, *parts)).encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest) / float(2**64)


@dataclass(frozen=True)
class Outcome:
    """Deterministic physics of one physical candidate call."""

    latency_ms: float
    acceptable: bool
    transient_failure: bool
    true_score: float
    noisy_score: float


def make_outcome_schedule(seed: int, specs: tuple[ModelSpec, ...]) -> Callable[[int, str], Outcome]:
    """Pure (task, model) -> Outcome map shared by every strategy.

    Because the map never reads strategy state, serial and parallel runs see
    byte-identical physics per candidate (common random numbers), which is
    what makes the strategy comparison meaningful. One task in every
    ``OUTAGE_PERIOD`` loses one provider for the whole task: correlated
    failure that heterogeneous candidates may or may not escape.
    """

    providers = [spec.provider for spec in specs]
    by_name = {spec.name: spec for spec in specs}

    def outage_provider(task: int) -> str | None:
        if task % OUTAGE_PERIOD:
            return None
        return providers[(task // OUTAGE_PERIOD) % len(providers)]

    def outcome(task: int, model: str) -> Outcome:
        spec = by_name[model]
        jitter = _uniform(seed, task, model, "latency")
        latency = spec.latency_ms * (1 - LATENCY_JITTER + 2 * LATENCY_JITTER * jitter)
        independent = _uniform(seed, task, model, "failure") < TRANSIENT_FAILURE_RATE
        transient = independent or outage_provider(task) == spec.provider
        acceptable = not transient and _uniform(seed, task, model, "pass") < spec.pass_rate
        quality_draw = _uniform(seed, task, model, "quality")
        if acceptable:
            true_score = _clamp01(spec.quality_mean * (0.85 + 0.3 * quality_draw))
        else:
            true_score = _clamp01(spec.quality_mean * 0.4 * quality_draw)
        noisy = _clamp01(
            true_score + (_uniform(seed, task, model, "verifier") - 0.5) * VERIFIER_NOISE
        )
        return Outcome(
            latency_ms=latency,
            acceptable=acceptable,
            transient_failure=transient,
            true_score=true_score,
            noisy_score=noisy,
        )

    return outcome


def effect_key(label: str, task: int, model: str) -> str:
    return f"spec:{label}:{task}:{model}"


@dataclass
class PhysicalCall:
    """One physical candidate call, recorded at the transport.

    ``state`` follows the transport lifecycle only: a call the strategy
    cancelled mid-flight stays ``in_flight`` here and is billed from the
    schedule at settle time, never erased.
    """

    task: int
    model: str
    provider: str
    effect_key: str
    latency_ms: float
    acceptable: bool
    transient_failure: bool
    true_score: float
    noisy_score: float
    input_units: int
    output_units: int
    state: str = "in_flight"
    billed_input: float = 0.0
    billed_output: float = 0.0


class SimulatedGateway:
    """The simulated provider physics, wired in as the gateway transport.

    No socket is opened: ``httpx.MockTransport`` is the repo's documented
    no-network seam, and the outbound guard deliberately lets fabricating
    transports through. Everything above the transport -- Binding resolution,
    Invocation admission, usage attribution, cancellation semantics -- is the
    real governed path.
    """

    def __init__(
        self,
        specs: tuple[ModelSpec, ...],
        outcome_of: Callable[[int, str], Outcome],
        *,
        label: str,
        scale: float,
    ) -> None:
        self._spec_by_name = {spec.name: spec for spec in specs}
        self._outcome_of = outcome_of
        self._label = label
        self._scale = scale
        self.records: list[PhysicalCall] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def records_for(self, task: int) -> list[PhysicalCall]:
        return [record for record in self.records if record.task == task]

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        model = str(payload["model"])
        task = int(str(payload["messages"][-1]["content"]).removeprefix("t"))
        spec = self._spec_by_name[model]
        outcome = self._outcome_of(task, model)
        record = PhysicalCall(
            task=task,
            model=model,
            provider=spec.provider,
            effect_key=effect_key(self._label, task, model),
            latency_ms=outcome.latency_ms,
            acceptable=outcome.acceptable,
            transient_failure=outcome.transient_failure,
            true_score=outcome.true_score,
            noisy_score=outcome.noisy_score,
            input_units=spec.input_units,
            output_units=spec.output_units,
        )
        self.records.append(record)
        await asyncio.sleep(outcome.latency_ms / 1000 * self._scale)
        if outcome.transient_failure:
            record.state = "failed"
            return httpx.Response(503, json={"error": "simulated provider failure"})
        record.state = "completed"
        return httpx.Response(
            200,
            json={
                "model": f"{model}-v1",
                "choices": [{"message": {"role": "assistant", "content": f"answer-t{task}"}}],
                "usage": {
                    "prompt_tokens": spec.input_units,
                    "completion_tokens": spec.output_units,
                },
            },
        )


@dataclass
class TaskOutcome:
    """What one strategy delivery returned for one task."""

    success: bool
    latency_ms: float
    delivered_score: float
    verifier_error: bool
    winner_effect_key: str | None
    winner_input: float = 0.0
    winner_output: float = 0.0


def _binding(model: str) -> Binding:
    return Binding(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        capability=MODEL_CHAT_CAPABILITY,
        provider_name=model,
        credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
    )


def _effects() -> Any:
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    effects.credentials.add(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="bench-litellm-key",
        ),
    )
    return effects


async def _governed_call(
    egress: ModelChatEgress,
    bindings: dict[str, Binding],
    label: str,
    task: int,
    model: str,
) -> ModelCallResult:
    """One pinned governed candidate call; duplicates stay distinct Invocations."""

    return await egress.complete(
        binding=bindings[model],
        run_id=label,
        node_run_id=f"t{task}",
        attempt_id="bench",
        effect_key=effect_key(label, task, model),
        request=ModelChatRequest(model=model, messages=[{"role": "user", "content": f"t{task}"}]),
    )


async def run_cascade(
    egress: ModelChatEgress,
    bindings: dict[str, Binding],
    chain: list[str],
    outcome_of: Callable[[int, str], Outcome],
    label: str,
    task: int,
) -> TaskOutcome:
    """Serial candidate chain: escalate on the first unacceptable answer.

    Also serves as ``single-strong`` with a one-model chain.
    """

    spent = 0.0
    for model in chain:
        outcome = outcome_of(task, model)
        with contextlib.suppress(Exception):
            await _governed_call(egress, bindings, label, task, model)
        spent += outcome.latency_ms
        if outcome.acceptable:
            return TaskOutcome(
                success=True,
                latency_ms=spent,
                delivered_score=outcome.true_score,
                verifier_error=False,
                winner_effect_key=effect_key(label, task, model),
            )
    return TaskOutcome(False, spent, 0.0, False, None)


async def run_early_stop(
    egress: ModelChatEgress,
    bindings: dict[str, Binding],
    models: list[str],
    outcome_of: Callable[[int, str], Outcome],
    label: str,
    task: int,
) -> TaskOutcome:
    """Launch every candidate; deliver the first acceptable completion."""

    outcomes = {model: outcome_of(task, model) for model in models}
    acceptable = [m for m in models if outcomes[m].acceptable]
    # On the simulated clock the earliest acceptable completion is known; the
    # strategy waits for exactly that call and cancels the rest.
    winner = min(acceptable, key=lambda m: (outcomes[m].latency_ms, m)) if acceptable else None
    tasks = {
        m: asyncio.create_task(_governed_call(egress, bindings, label, task, m)) for m in models
    }
    if winner is None:
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        return TaskOutcome(
            False,
            max(outcomes[m].latency_ms for m in models),
            0.0,
            False,
            None,
        )
    with contextlib.suppress(Exception):
        await tasks[winner]
    losers = [t for m, t in tasks.items() if m != winner]
    for loser in losers:
        loser.cancel()
    await asyncio.gather(*losers, return_exceptions=True)
    won = outcomes[winner]
    return TaskOutcome(
        success=True,
        latency_ms=won.latency_ms,
        delivered_score=won.true_score,
        verifier_error=False,
        winner_effect_key=effect_key(label, task, winner),
    )


async def run_verifier(
    egress: ModelChatEgress,
    bindings: dict[str, Binding],
    models: list[str],
    outcome_of: Callable[[int, str], Outcome],
    label: str,
    task: int,
) -> TaskOutcome:
    """Launch every candidate, wait for all, let a noisy verifier select."""

    outcomes = {model: outcome_of(task, model) for model in models}
    tasks = [asyncio.create_task(_governed_call(egress, bindings, label, task, m)) for m in models]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    answered = [
        m
        for m, result in zip(models, results, strict=True)
        if not isinstance(result, BaseException)
    ]
    acceptable = [m for m in answered if outcomes[m].acceptable]
    latency = max(outcomes[m].latency_ms for m in models)
    if not acceptable:
        return TaskOutcome(False, latency, 0.0, False, None)
    picked = max(acceptable, key=lambda m: (outcomes[m].noisy_score, m))
    best_true = max(outcomes[m].true_score for m in acceptable)
    error = outcomes[picked].true_score < best_true - 1e-12
    return TaskOutcome(
        success=True,
        latency_ms=latency,
        delivered_score=outcomes[picked].true_score,
        verifier_error=error,
        winner_effect_key=effect_key(label, task, picked),
    )


def _settle_billing(records: list[PhysicalCall], outcome: TaskOutcome) -> None:
    """Charge every physical call from the deterministic schedule.

    Completed calls bill input + full output; transient-failed calls bill
    input only; calls still in flight when the winner landed bill input plus
    the output accrued by the winner's completion time (linear progress).
    """

    if outcome.winner_effect_key is None:
        # Nothing delivered: every launched call is pure waste.
        for record in records:
            if record.state == "failed":
                record.billed_input = float(record.input_units)
            else:
                record.billed_input = float(record.input_units)
                record.billed_output = float(record.output_units)
        return
    for record in records:
        if record.effect_key == outcome.winner_effect_key:
            record.billed_input = float(record.input_units)
            record.billed_output = float(record.output_units)
            outcome.winner_input = record.billed_input
            outcome.winner_output = record.billed_output
        elif record.state == "failed":
            record.billed_input = float(record.input_units)
        else:
            record.billed_input = float(record.input_units)
            if record.state == "completed":
                record.billed_output = float(record.output_units)
            else:  # cancelled mid-flight by the strategy
                progress = min(outcome.latency_ms / record.latency_ms, 1.0)
                record.billed_output = float(record.output_units) * progress


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[max(index, 0)]


@dataclass
class StrategySummary:
    strategy: str
    topology: str
    tasks: int
    p50_ms: float
    p95_ms: float
    mean_latency_ms: float
    success_rate: float
    mean_delivered_score: float
    input_units: float
    output_units: float
    cost_cents: float
    wasted_units: float
    cancelled_units: float
    wasted_cost_cents: float
    physical_calls: int
    invocations_completed: int
    invocations_unknown: int
    invocations_recorded: int
    outage_tasks: int
    outage_success_rate: float
    verifier_errors: int
    verifier_error_rate: float
    chain: list[str]


def _cost(
    spec_by_name: dict[str, ModelSpec], model: str, input_units: float, output_units: float
) -> float:
    spec = spec_by_name[model]
    return (
        input_units / 1000 * spec.cost_per_1k_input + output_units / 1000 * spec.cost_per_1k_output
    )


async def count_invocations(
    effects: Any,
    bindings: dict[str, Binding],
    records: list[PhysicalCall],
    label: str,
) -> dict[str, int]:
    """Audit the Invocation ledger against the transport's call records.

    Every physical call must own exactly one governed Invocation: a count
    mismatch means a duplicate was hidden, which this benchmark refuses to do.
    """

    counts = {"completed": 0, "unknown": 0, "other": 0, "recorded": 0}
    for record in records:
        history = await effects.invocation_store.list_effect(
            run_id=label,
            node_run_id=f"t{record.task}",
            binding_id=bindings[record.model].binding_id,
            effect_key=record.effect_key,
        )
        if len(history) != 1:
            raise RuntimeError(
                f"physical call {record.effect_key} recorded {len(history)} Invocations; "
                "duplicated calls must stay visible, never merged or hidden"
            )
        counts["recorded"] += 1
        status = history[0].status
        if status is InvocationStatus.COMPLETED:
            counts["completed"] += 1
        elif status is InvocationStatus.UNKNOWN:
            counts["unknown"] += 1
        else:
            counts["other"] += 1
    return counts


async def run_strategy(
    strategy: str,
    topology: str,
    tasks_n: int,
    *,
    seed: int,
    scale: float,
    outcome_of: Callable[[int, str], Outcome] | None = None,
) -> StrategySummary:
    """Run one strategy over the fixed workload and summarize the delivery.

    ``outcome_of`` overrides the seeded physics so tests can pin exact
    outcomes through this real entry point instead of guessing statistics.
    """

    specs = catalog_for(topology)
    spec_by_name = {spec.name: spec for spec in specs}
    outcome_of = outcome_of or make_outcome_schedule(seed, specs)
    registry = build_registry(specs)
    router = CostAwareRouter(registry)
    chain = [model.name for model in await router.fallback_chain(CHAIN_HEAD)]
    models = [spec.name for spec in specs]
    label = f"{strategy}-{topology}"
    gateway = SimulatedGateway(specs, outcome_of, label=label, scale=scale)

    set_test_transport(gateway.transport())
    try:
        effects = _effects()
        egress = ModelChatEgress(effects, registry=registry, router=router, endpoint=ENDPOINT)
        bindings = {spec.name: _binding(spec.name) for spec in specs}
        outcomes: list[TaskOutcome] = []
        for task in range(tasks_n):
            if strategy == "serial-fallback":
                outcomes.append(await run_cascade(egress, bindings, chain, outcome_of, label, task))
            elif strategy == "single-strong":
                outcomes.append(
                    await run_cascade(egress, bindings, [models[-1]], outcome_of, label, task)
                )
            elif strategy == "parallel-early-stop":
                outcomes.append(
                    await run_early_stop(egress, bindings, models, outcome_of, label, task)
                )
            elif strategy == "parallel-verifier":
                outcomes.append(
                    await run_verifier(egress, bindings, models, outcome_of, label, task)
                )
            else:
                raise ValueError(f"unknown strategy {strategy!r}")
        for task, outcome in enumerate(outcomes):
            _settle_billing(gateway.records_for(task), outcome)
        invocation_counts = await count_invocations(effects, bindings, gateway.records, label)
    finally:
        set_test_transport(None)

    latencies = [outcome.latency_ms for outcome in outcomes]
    input_units = sum(r.billed_input for r in gateway.records)
    output_units = sum(r.billed_output for r in gateway.records)
    cost = sum(
        _cost(spec_by_name, r.model, r.billed_input, r.billed_output) for r in gateway.records
    )
    winners = {o.winner_effect_key for o in outcomes} - {None}
    wasted_records = [r for r in gateway.records if r.effect_key not in winners]
    wasted_cost = sum(
        _cost(spec_by_name, r.model, r.billed_input, r.billed_output) for r in wasted_records
    )
    wasted_units = sum(r.billed_input + r.billed_output for r in wasted_records)
    cancelled_units = sum(
        r.billed_input + r.billed_output for r in gateway.records if r.state == "in_flight"
    )
    outage_indices = range(0, tasks_n, OUTAGE_PERIOD)
    outage_successes = sum(outcomes[task].success for task in outage_indices)

    return StrategySummary(
        strategy=strategy,
        topology=topology,
        tasks=tasks_n,
        p50_ms=round(_percentile(latencies, 50), 1),
        p95_ms=round(_percentile(latencies, 95), 1),
        mean_latency_ms=round(sum(latencies) / max(len(latencies), 1), 1),
        success_rate=round(sum(o.success for o in outcomes) / max(tasks_n, 1), 4),
        mean_delivered_score=round(sum(o.delivered_score for o in outcomes) / max(tasks_n, 1), 4),
        input_units=round(input_units, 1),
        output_units=round(output_units, 1),
        cost_cents=round(cost, 4),
        wasted_units=round(wasted_units, 1),
        cancelled_units=round(cancelled_units, 1),
        wasted_cost_cents=round(wasted_cost, 4),
        physical_calls=len(gateway.records),
        invocations_completed=invocation_counts["completed"],
        invocations_unknown=invocation_counts["unknown"],
        invocations_recorded=invocation_counts["recorded"],
        outage_tasks=len(outage_indices),
        outage_success_rate=round(outage_successes / max(len(outage_indices), 1), 4),
        verifier_errors=sum(o.verifier_error for o in outcomes),
        verifier_error_rate=round(sum(o.verifier_error for o in outcomes) / max(tasks_n, 1), 4),
        chain=chain,
    )


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=DEFAULT_TASKS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--scale", type=float, default=DEFAULT_SCALE)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.tasks < 1:
        parser.error("--tasks must be >= 1")
    if args.scale <= 0:
        parser.error("--scale must be > 0 (0 would collapse the simulated clock)")

    results = []
    for topology in ("diverse", "same"):
        for strategy in STRATEGY_ORDER:
            summary = await run_strategy(
                strategy, topology, args.tasks, seed=args.seed, scale=args.scale
            )
            results.append(asdict(summary))
            print(
                f"{summary.topology:>7}/{summary.strategy:<20} "
                f"p50={summary.p50_ms:>7.1f}ms p95={summary.p95_ms:>8.1f}ms "
                f"success={summary.success_rate:.3f} score={summary.mean_delivered_score:.3f} "
                f"cost={summary.cost_cents:>8.2f}c wasted={summary.wasted_units:>9.0f}u "
                f"({summary.wasted_cost_cents:.2f}c) "
                f"outage_success={summary.outage_success_rate:.3f} "
                f"verifier_err={summary.verifier_error_rate:.3f} "
                f"calls={summary.physical_calls} invocations={summary.invocations_recorded}",
                flush=True,
            )

    payload = {
        "benchmark": "speculative-parallel-model-calls",
        "issue": "917",
        "epic": "900",
        "seed": args.seed,
        "tasks": args.tasks,
        "scale": args.scale,
        "outage_period": OUTAGE_PERIOD,
        "transient_failure_rate": TRANSIENT_FAILURE_RATE,
        "verifier_noise": VERIFIER_NOISE,
        "latency_jitter": LATENCY_JITTER,
        "catalog": [asdict(spec) for spec in DIVERSE_CATALOG],
        "results": results,
    }
    if args.output:
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
