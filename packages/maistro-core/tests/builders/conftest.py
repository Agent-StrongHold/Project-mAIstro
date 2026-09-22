"""Builders test-suite fixtures, including the frozen legacy parity oracle.

`GraphPipelineExecutor` was the pre-#734 in-process Builders executor. The
shipped ``maistro.builders`` package no longer carries it: production Builders
composition executes through ``CanonicalGraphPipelineExecutor`` on the
canonical Graph -> Run -> NodeRun -> Attempt spine, and a legacy executor that
remained importable from the product package kept a second, canonical-evidence
-free execution authority reachable (M1 closure-safety rule: the old authority
must be unable to win).

The implementation below is the verbatim retirement copy. It exists only so
the behavioral contract tests can still compare canonical execution outcomes
against the executor it replaced; nothing outside this test suite can import
or construct it.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from typing import TYPE_CHECKING, Any

import pytest

from maistro.builders.graph_executor import _build_prompt
from maistro.graph.node import IterationBudget

if TYPE_CHECKING:
    from maistro.builders.graph import PipelineGraph, PipelineNode
    from maistro.builders.graph_executor import PipelineDispatcher

logger = logging.getLogger("maistro.builders.graph_executor")

_DEFAULT_EXECUTIONS_PER_NODE = 3

__all__ = ["GraphPipelineExecutor", "legacy_graph_executor"]


class _Outcome(enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    GATE_FAILED = "gate_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class _GateRoute(enum.Enum):
    REVISE = "revise"
    PROCEED = "proceed"
    HALT = "halt"


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
    """Legacy in-process parity executor; production uses the canonical adapter.

    Kept for behavioral comparison in the Builders contract tests while the
    public Builders package no longer exports it as a product composition.
    """

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


@pytest.fixture
def legacy_graph_executor() -> type[GraphPipelineExecutor]:
    """Hand test code the retired executor without re-shipping it (#734/M1)."""
    return GraphPipelineExecutor
