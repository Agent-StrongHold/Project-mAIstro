"""Graph-aware builder pipeline executor.

Drives a :class:`~maistro.builders.graph.PipelineGraph` to completion:
find ready nodes → check skip → dispatch the whole wave concurrently →
store outputs → evaluate gates → repeat until no ready nodes remain.

Differences from the Stronghold Epic-15 executor it recreates:

- Dispatch is a direct ``await`` against a :class:`PipelineDispatcher`
  protocol instead of an engine poll loop; timeouts use ``asyncio.timeout``.
- Independent ready nodes execute concurrently (Epic-15 modelled the
  parallelism but ran the ready set sequentially).
- A failed gate triggers a bounded verify-and-revise loop: the revise
  target and every completed descendant are cleared and re-executed with
  the gating node's output injected as ``<node>_feedback``.
- Every node execution consumes from a shared
  :class:`~maistro.graph.node.IterationBudget` (ADR-062); exhaustion halts
  the run gracefully.

Failure still halts the run before any *new* node starts (Epic-15 INV-07,
relaxed to wave granularity), and a timed-out node never runs its
``on_complete`` hook (INV-09).
"""

from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from maistro.graph.node import IterationBudget

if TYPE_CHECKING:
    from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext

logger = logging.getLogger("maistro.builders.graph_executor")

_DEFAULT_EXECUTIONS_PER_NODE = 3


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of dispatching one node to an agent."""

    ok: bool
    output: str = ""
    error: str = ""


class PipelineDispatcher(Protocol):
    """Seam between the executor and whatever runs the agents."""

    def supports(self, agent_name: str, node_name: str) -> bool:
        """Whether this dispatcher can execute the named agent for this node."""
        ...

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> DispatchResult:
        """Execute one node and return its outcome."""
        ...


class _Outcome(enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    GATE_FAILED = "gate_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class _GateRoute(enum.Enum):
    REVISE = "revise"
    PROCEED = "proceed"
    HALT = "halt"


class GraphPipelineExecutor:
    """Drive a PipelineGraph to completion."""

    def __init__(
        self,
        dispatcher: PipelineDispatcher,
        *,
        budget: IterationBudget | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._budget = budget

    async def execute(self, graph: PipelineGraph, run: Any) -> Any:
        """Drive the graph to completion. Returns run with updated status/context."""
        errors = graph.validate()
        if errors:
            run.status = f"invalid graph: {'; '.join(errors)}"
            return run

        run.status = "running"
        budget = self._budget or IterationBudget(
            max_iterations=_DEFAULT_EXECUTIONS_PER_NODE * len(graph)
        )
        completed: set[str] = set()
        skipped: set[str] = set()
        revisions: dict[str, int] = {}

        while True:
            ready = graph.ready(frozenset(completed), frozenset(skipped))
            if not ready:
                break

            wave = self._partition_wave(ready, run, skipped)
            if not wave:
                continue

            outcomes = await asyncio.gather(*(self._run_node(node, run, budget) for node in wave))
            if not self._apply_wave_outcomes(
                graph, wave, outcomes, run, revisions, completed, skipped
            ):
                return run

        if run.status == "running":
            run.status = "completed"
        return run

    def _partition_wave(
        self, ready: list[PipelineNode], run: Any, skipped: set[str]
    ) -> list[PipelineNode]:
        """Mark skippable ready nodes as skipped; return the nodes to dispatch."""
        wave: list[PipelineNode] = []
        for node in ready:
            if node.skip_if is not None and node.skip_if(run.context):
                logger.info("Executor: skipping %s (skip_if)", node.name)
                skipped.add(node.name)
                run.skipped_stages.append(node.name)
            elif not self._dispatcher.supports(node.agent_name, node.name):
                logger.warning(
                    "Executor: skipping %s (agent %r not available)",
                    node.name,
                    node.agent_name,
                )
                skipped.add(node.name)
                run.skipped_stages.append(node.name)
            else:
                wave.append(node)
        return wave

    def _apply_wave_outcomes(
        self,
        graph: PipelineGraph,
        wave: list[PipelineNode],
        outcomes: list[_Outcome],
        run: Any,
        revisions: dict[str, int],
        completed: set[str],
        skipped: set[str],
    ) -> bool:
        """Fold one wave's outcomes into the run. Returns False to halt."""
        # Record completions first so a same-wave gate failure clears
        # stale descendants consistently.
        gate_failures: list[PipelineNode] = []
        for node, outcome in zip(wave, outcomes, strict=True):
            if outcome is _Outcome.COMPLETED:
                completed.add(node.name)
            elif outcome is _Outcome.GATE_FAILED:
                gate_failures.append(node)
            elif outcome is _Outcome.BUDGET_EXHAUSTED:
                run.status = f"halted at {node.name}: iteration budget exhausted"
                return False
            else:
                return False

        for node in gate_failures:
            route = self._route_gate_failure(graph, node, run, revisions, completed, skipped)
            if route is _GateRoute.PROCEED:
                completed.add(node.name)
            elif route is _GateRoute.HALT:
                return False
            # REVISE: stale nodes were cleared; the next ready() pass
            # re-offers them.
        return True

    def _route_gate_failure(
        self,
        graph: PipelineGraph,
        node: PipelineNode,
        run: Any,
        revisions: dict[str, int],
        completed: set[str],
        skipped: set[str],
    ) -> _GateRoute:
        """Decide what a failed gate means for the run."""
        used = revisions.get(node.name, 0)
        if used >= node.max_revisions:
            if node.gate_exhausted == "continue":
                logger.warning(
                    "Executor: %s gate still failing after %d revisions; continuing",
                    node.name,
                    used,
                )
                run.gate_exhausted.append(node.name)
                return _GateRoute.PROCEED
            run.status = f"failed at {node.name}"
            run.failed_stage_error = f"Gate failed after {used} revisions"
            logger.error("Executor: %s gate exhausted after %d revisions", node.name, used)
            return _GateRoute.HALT

        revisions[node.name] = used + 1
        run.revisions = dict(revisions)
        # validate() guarantees revise_target is a present ancestor.
        target = node.revise_target or ""
        stale = {target} | set(graph.descendants(target))
        completed.difference_update(stale)
        skipped.difference_update(stale)
        run.skipped_stages[:] = [s for s in run.skipped_stages if s not in stale]
        feedback = run.context.get(node.name, "")
        for name in stale:
            run.context.pop(name, None)
        run.context[f"{node.name}_feedback"] = feedback
        logger.info(
            "Executor: %s gate failed (revision %d/%d) — re-running from %s",
            node.name,
            revisions[node.name],
            node.max_revisions,
            target,
        )
        return _GateRoute.REVISE

    async def _run_node(self, node: PipelineNode, run: Any, budget: IterationBudget) -> _Outcome:
        if not budget.consume():
            logger.error("Executor: %s halted — iteration budget exhausted", node.name)
            return _Outcome.BUDGET_EXHAUSTED

        prompt = _build_prompt(node.prompt_template, run.context)

        try:
            async with asyncio.timeout(node.timeout_seconds):
                result = await self._dispatcher.run(
                    run_id=run.id,
                    node_name=node.name,
                    agent_name=node.agent_name,
                    prompt=prompt,
                    context=run.context,
                )
        except TimeoutError:
            run.status = f"failed at {node.name}"
            run.failed_stage_error = f"Stage timed out after {node.timeout_seconds:.0f}s"
            logger.error("Executor: %s TIMED OUT", node.name)
            return _Outcome.FAILED

        if not result.ok:
            run.status = f"failed at {node.name}"
            run.failed_stage_error = result.error
            logger.error("Executor: %s FAILED: %s", node.name, result.error)
            return _Outcome.FAILED

        run.context[node.name] = result.output

        if node.on_complete is not None:
            await node.on_complete(run, result.output)

        if run.status.startswith("failed at "):
            return _Outcome.FAILED

        if node.gate is not None and not node.gate(run.context):
            return _Outcome.GATE_FAILED

        logger.info("Executor: %s completed", node.name)
        return _Outcome.COMPLETED


def _build_prompt(template: str, context: RunContext) -> str:
    class _Default(dict):  # type: ignore[type-arg]
        def __missing__(self, key: str) -> str:
            return ""

    try:
        return template.format_map(_Default(context))
    except (ValueError, KeyError):
        return template
