"""`HarnessAdapter` (maistro.graph.harness) wrapping an RSI cycle.

`RsiCycle.run(baseline, candidate, available_models)` is a single long-running
coroutine — clone, branch, patch, test, evaluate, battle — rather than its own
dispatch/poll primitive. This adapter is the seam: `dispatch` starts it as a
background asyncio task and returns immediately (the calling DAG node then
pauses, same as every other harness); `poll` checks whether it has finished
and translates an `RsiCycleResult` into a `HarnessResult`; `cancel` tears down
an in-flight attempt.

`HarnessRequest.context["num_cycles"]` (default 1, from `rsi.quota_pace_trigger`'s
paced count) runs that many independent `RsiCycle.run()` attempts *concurrently*
under one handle — parallel, not sequential, since each cycle is an independent
attempt at the same improvement goal rather than a chain where only the last
matters. `poll` waits for all of them, aggregates into one `HarnessResult`
(`success` if any cycle improved), and `cancel` tears down every in-flight task.

A dispatched RSI cycle is exactly the kind of self-modifying work
`maistro_rsi.quarantine` exists to gate — this adapter dispatches the cycle,
it does not itself decide whether the cycle's diff is safe to promote; that's
`RsiCycle.run`'s own `quarantine_check` plumbing (see `runner.py`/`SPEC.md`).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

from maistro.graph.harness import HarnessHandle, HarnessRequest, HarnessResult
from maistro_evolve.types import PipelineGenome

if TYPE_CHECKING:
    from maistro_rsi.runner import RsiCycleResult

logger = structlog.get_logger()


@runtime_checkable
class RsiCycleRunner(Protocol):
    """What the adapter needs from an RSI cycle — `RsiCycle.run` satisfies this
    structurally, but depending on the protocol (not the concrete class) keeps
    this module free of the sandbox/git/tournament import chain and makes the
    adapter trivially testable with a fake."""

    async def run(
        self,
        baseline: PipelineGenome,
        candidate: PipelineGenome,
        available_models: list[str],
    ) -> RsiCycleResult: ...


@dataclass
class _InFlight:
    tasks: list[asyncio.Task[RsiCycleResult]]
    deadline: float


def _cancel(task: asyncio.Task[RsiCycleResult]) -> None:
    """Cancel a task whose result nobody will ever await directly, and make
    sure asyncio doesn't log an "exception was never retrieved" warning for
    whatever the cancelled coroutine unwinds into."""
    if task.done():
        return
    task.cancel()
    task.add_done_callback(_drain)


def _drain(task: asyncio.Task[RsiCycleResult]) -> None:
    if not task.cancelled():
        task.exception()  # retrieve + discard


def _coerce_genome(value: Any, field_name: str) -> PipelineGenome:
    """Accept a live `PipelineGenome` (in-process dispatch, e.g. from a test
    or a caller composing one directly) or a plain `dict` (a persisted/JSON-
    deserialized durable DAG's `HarnessRequest.context` -- `PipelineGenome`
    is a Pydantic model, so `model_validate` is the right coercion). Any
    other type is a genuine caller error, same as before this accepted dicts."""
    if isinstance(value, PipelineGenome):
        return value
    if isinstance(value, dict):
        return PipelineGenome.model_validate(value)
    raise ValueError(
        f"RsiCycleHarnessAdapter requires context['{field_name}'] to be a "
        f"PipelineGenome or dict, got {type(value).__name__}"
    )


def _aggregate_results_to_harness_result(
    handle_id: str, results: list[RsiCycleResult], errors: list[str]
) -> HarnessResult:
    """Combine N parallel `RsiCycleResult`s into one `HarnessResult`. Parallel
    cycles are independent attempts at the same improvement goal, not a
    sequence where only the last matters -- success if *any* cycle improved."""
    improved = [r for r in results if r.improved]
    total_benchmarks_won = sum(r.benchmarks_won for r in results)
    total_battles = sum(len(r.battles) for r in results)
    cycles_summary = [
        {
            "run_id": r.run_id,
            "model_used": r.model_used,
            "tests_passed": r.branch_result.tests_passed,
            "benchmarks_won": r.benchmarks_won,
            "battles_total": len(r.battles),
            "pr_url": r.branch_result.pr_url,
            "improved": r.improved,
        }
        for r in results
    ]
    return HarnessResult(
        handle_id=handle_id,
        success=bool(improved),
        output=(
            f"cycles_completed={len(results)}/{len(results) + len(errors)} "
            f"cycles_improved={len(improved)} benchmarks_won={total_benchmarks_won}/{total_battles}"
        ),
        error=None if results else ("; ".join(errors) or "all cycles failed"),
        metadata={
            "cycles": cycles_summary,
            "cycles_completed": len(results),
            "cycles_improved": len(improved),
            "cycles_failed": len(errors),
            "errors": errors,
        },
    )


class RsiCycleHarnessAdapter:
    """Dispatches one or more RSI cycles as background tasks.

    `cycle` is a single, reusable `RsiCycleRunner` (`RsiCycle` in production)
    "recipe" object — `run()` mints its own `run_id`/workspace per call, so
    nothing about it is per-dispatch state and one instance safely serves
    many concurrent dispatches.

    Each `HarnessRequest.context` must carry `baseline_genome` and
    `candidate_genome` (a `PipelineGenome` instance or an equivalent `dict`)
    and `available_models` (`list[str]`) — the actual arguments `RsiCycle.run`
    needs. Missing any of these is a caller error, not a runtime failure to
    gate silently, so `dispatch` raises rather than swallowing it.
    `context["num_cycles"]` (default 1) runs that many independent cycles
    concurrently under one handle -- see module docstring.
    """

    def __init__(self, cycle: RsiCycleRunner) -> None:
        self._cycle = cycle
        self._in_flight: dict[str, _InFlight] = {}

    async def dispatch(self, request: HarnessRequest) -> HarnessHandle:
        baseline = _coerce_genome(request.context.get("baseline_genome"), "baseline_genome")
        candidate = _coerce_genome(request.context.get("candidate_genome"), "candidate_genome")
        available_models = request.context.get("available_models")
        if not isinstance(available_models, list):
            raise ValueError(
                "RsiCycleHarnessAdapter requires context['available_models']: list[str]"
            )
        num_cycles = int(request.context.get("num_cycles", 1))

        handle_id = uuid.uuid4().hex[:12]
        tasks = [
            asyncio.create_task(self._cycle.run(baseline, candidate, available_models))
            for _ in range(num_cycles)
        ]
        self._in_flight[handle_id] = _InFlight(
            tasks=tasks, deadline=time.monotonic() + request.timeout_seconds
        )
        await logger.ainfo("rsi_harness_dispatched", handle_id=handle_id, num_cycles=num_cycles)
        return HarnessHandle(handle_id=handle_id, harness_type="rsi_cycle")

    async def poll(self, handle: HarnessHandle) -> HarnessResult | None:
        in_flight = self._in_flight.get(handle.handle_id)
        if in_flight is None:
            return HarnessResult(
                handle_id=handle.handle_id, success=False, output="", error="unknown handle"
            )

        if not all(t.done() for t in in_flight.tasks):
            if time.monotonic() < in_flight.deadline:
                return None
            for t in in_flight.tasks:
                _cancel(t)
            del self._in_flight[handle.handle_id]
            return HarnessResult(
                handle_id=handle.handle_id, success=False, output="", error="timed out"
            )

        del self._in_flight[handle.handle_id]

        if not in_flight.tasks:
            # num_cycles<=0 (e.g. the quota pacer signalling no headroom) is a
            # deliberate no-op, not a failure -- must not read as "all cycles
            # failed" (the aggregation path's message for an empty result set).
            return HarnessResult(
                handle_id=handle.handle_id,
                success=True,
                output="no cycles dispatched (num_cycles<=0)",
                error=None,
                metadata={
                    "cycles": [],
                    "cycles_completed": 0,
                    "cycles_improved": 0,
                    "cycles_failed": 0,
                    "errors": [],
                },
            )

        results: list[RsiCycleResult] = []
        errors: list[str] = []
        for t in in_flight.tasks:
            if t.cancelled():
                errors.append("cancelled")
                continue
            exc = t.exception()
            if exc is not None:
                await logger.awarning(
                    "rsi_harness_cycle_failed", handle_id=handle.handle_id, error=str(exc)
                )
                errors.append(str(exc))
                continue
            results.append(t.result())

        return _aggregate_results_to_harness_result(handle.handle_id, results, errors)

    async def cancel(self, handle: HarnessHandle) -> None:
        in_flight = self._in_flight.pop(handle.handle_id, None)
        if in_flight is not None:
            for t in in_flight.tasks:
                _cancel(t)
