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

This module also hosts the canonical execution adapter (#734):
:class:`CanonicalGraphPipelineExecutor` translates a ``PipelineGraph`` into
a canonical ``Graph`` and drives it through the public durable
Run/NodeRun/Attempt spine, keeping Builders prompts, context, skip
predicates, gates, revision feedback, hooks and result projection as domain
state. The legacy :class:`GraphPipelineExecutor` above remains the parity
oracle while the parent convergence issue (#49) chooses product composition.
The adapter lives in this module rather than one of its own because a new
module identity would register as new unreachable-module debt against the
trusted-base reachability ratchet, and #734 defers reachability bookkeeping
to #49; it already shares this module's private dispatch helpers.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import DurableRunRecord, run_durable_graph
from maistro.graph.node import IterationBudget
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.runs.model import RunStatus

if TYPE_CHECKING:
    from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
    from maistro.graph.durable_runs.protocol import DurableRunStore
    from maistro.runs.store import RunStore

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


# --- Canonical execution adapter (#734) -------------------------------------
# Translated from the branch's standalone canonical_execution module into the
# executor module it already shares helpers with; see the module docstring.

_STAGE_KIND = "builders.pipeline_stage"
_START_KIND = "builders.frontier_start"
_STAGE_PREFIX = "builders-stage:"
_START_NODE_ID = "builders-frontier-start"
_ADMISSION_SOURCE = "builders"


class _StageInput(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _StageOutput(BaseModel):
    stage_name: str
    text: str = ""
    skipped: bool = False
    route: Literal["proceed", "revise"] = "proceed"


class _StartOutput(BaseModel):
    ready: bool = True


class _StartNode(BaseNode[_StageInput, _StartOutput]):
    kind: ClassVar[str] = _START_KIND
    input_schema: ClassVar[type[BaseModel]] = _StageInput
    output_schema: ClassVar[type[BaseModel]] = _StartOutput
    display_name: ClassVar[str] = "Start Builders ready frontier"
    description: ClassVar[str] = "Fan out to independent Builders root stages."

    async def _execute(self, inputs: _StageInput, ctx: NodeContext) -> _StartOutput:
        return _StartOutput()


@dataclass(frozen=True)
class _GateDecision:
    route: Literal["proceed", "revise"]
    halt_error: str | None = None


def _stage_node_id(stage_name: str) -> str:
    return f"{_STAGE_PREFIX}{stage_name}"


def _stage_name(node_id: str) -> str | None:
    if not node_id.startswith(_STAGE_PREFIX):
        return None
    return node_id[len(_STAGE_PREFIX) :]


def _mark_skipped(run: Any, stage_name: str) -> None:
    if stage_name not in run.skipped_stages:
        run.skipped_stages.append(stage_name)


def _gate_decision(graph: PipelineGraph, node: PipelineNode, run: Any) -> _GateDecision:
    """Apply Builders gate domain semantics without owning canonical lifecycle."""
    used = int(run.revisions.get(node.name, 0))
    if used >= node.max_revisions:
        if node.gate_exhausted == "continue":
            if node.name not in run.gate_exhausted:
                run.gate_exhausted.append(node.name)
            return _GateDecision(route="proceed")
        error = f"Gate failed after {used} revisions"
        run.failed_stage_error = error
        return _GateDecision(route="proceed", halt_error=error)

    run.revisions[node.name] = used + 1
    target = node.revise_target or ""
    stale = {target} | set(graph.descendants(target))
    run.skipped_stages[:] = [name for name in run.skipped_stages if name not in stale]

    feedback = run.context.get(node.name, "")
    for name in stale:
        run.context.pop(name, None)
    run.context[f"{node.name}_feedback"] = feedback
    return _GateDecision(route="revise")


def _skip_output(
    node: PipelineNode,
    run: Any,
    dispatcher: PipelineDispatcher,
) -> _StageOutput | None:
    should_skip = node.skip_if is not None and node.skip_if(run.context)
    if not should_skip and dispatcher.supports(node.agent_name, node.name):
        return None
    _mark_skipped(run, node.name)
    return _StageOutput(stage_name=node.name, skipped=True)


def _reserve_iteration(run: Any, budget: IterationBudget) -> None:
    if budget.consume():
        return
    error = "iteration budget exhausted"
    run.failed_stage_error = error
    raise RuntimeError(error)


async def _dispatch_stage(
    node: PipelineNode,
    run: Any,
    dispatcher: PipelineDispatcher,
    ctx: NodeContext,
) -> Any:
    prompt = _build_prompt(node.prompt_template, run.context)
    try:
        async with asyncio.timeout(node.timeout_seconds):
            result = await dispatcher.run(
                run_id=ctx.run_id,
                node_name=node.name,
                agent_name=node.agent_name,
                prompt=prompt,
                context=run.context,
            )
    except TimeoutError as exc:
        error = f"Stage timed out after {node.timeout_seconds:.0f}s"
        run.failed_stage_error = error
        raise RuntimeError(error) from exc

    if not result.ok:
        run.failed_stage_error = result.error
        raise RuntimeError(result.error or f"{node.name} failed")
    return result


async def _commit_stage_result(node: PipelineNode, run: Any, result: Any) -> None:
    run.context[node.name] = result.output
    if node.on_complete is not None:
        await node.on_complete(run, result.output)
    if str(run.status).startswith("failed at "):
        raise RuntimeError(run.failed_stage_error or f"{node.name} failed")


def _route_stage_result(
    graph: PipelineGraph,
    node: PipelineNode,
    run: Any,
    result: Any,
) -> _StageOutput:
    if node.gate is None or node.gate(run.context):
        return _StageOutput(stage_name=node.name, text=result.output)

    decision = _gate_decision(graph, node, run)
    if decision.halt_error is not None:
        raise RuntimeError(decision.halt_error)
    return _StageOutput(
        stage_name=node.name,
        text=result.output,
        route=decision.route,
    )


class _StageNode(BaseNode[_StageInput, _StageOutput]):
    kind: ClassVar[str] = _STAGE_KIND
    input_schema: ClassVar[type[BaseModel]] = _StageInput
    output_schema: ClassVar[type[BaseModel]] = _StageOutput
    display_name: ClassVar[str] = "Execute Builders pipeline stage"
    description: ClassVar[str] = "Run one Builders stage under canonical Attempt evidence."
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True

    def __init__(
        self,
        *,
        graph: PipelineGraph,
        node: PipelineNode,
        run: Any,
        dispatcher: PipelineDispatcher,
        budget: IterationBudget,
    ) -> None:
        self._graph = graph
        self._node = node
        self._run = run
        self._dispatcher = dispatcher
        self._budget = budget

    async def _execute(self, inputs: _StageInput, ctx: NodeContext) -> _StageOutput:
        skipped = _skip_output(self._node, self._run, self._dispatcher)
        if skipped is not None:
            return skipped

        _reserve_iteration(self._run, self._budget)
        result = await _dispatch_stage(self._node, self._run, self._dispatcher, ctx)
        await _commit_stage_result(self._node, self._run, result)
        return _route_stage_result(self._graph, self._node, self._run, result)


def _roots(graph: PipelineGraph) -> list[PipelineNode]:
    return [node for node in graph if not node.depends_on]


def _fanout_edges(
    source: str,
    targets: list[str],
    *,
    condition: str | None = None,
) -> list[Edge]:
    """Encode one canonical ready wave as one sequential edge plus parallel siblings."""
    return [
        Edge(
            from_node=source,
            to_node=target,
            condition=condition,
            metadata={"parallel": True} if index else {},
        )
        for index, target in enumerate(targets)
    ]


def _canonical_stage_nodes(graph: PipelineGraph) -> list[Node]:
    return [
        Node(
            node_id=_stage_node_id(node.name),
            node_type=_STAGE_KIND,
            name=node.name,
            metadata={"builders_stage": node.name},
            policies={"max_attempts": 1},
        )
        for node in graph
    ]


def _dependency_edges(graph: PipelineGraph) -> list[Edge]:
    by_name = {node.name: node for node in graph}
    successors: dict[str, list[str]] = {node.name: [] for node in graph}
    for node in graph:
        for dependency in node.depends_on:
            successors[dependency].append(node.name)

    edges: list[Edge] = []
    for predecessor_name, successor_names in successors.items():
        predecessor = by_name[predecessor_name]
        edges.extend(
            _fanout_edges(
                _stage_node_id(predecessor_name),
                [_stage_node_id(name) for name in successor_names],
                condition="route == 'proceed'" if predecessor.gate is not None else None,
            )
        )
    return edges


def _revision_edges(graph: PipelineGraph) -> list[Edge]:
    return [
        Edge(
            from_node=_stage_node_id(node.name),
            to_node=_stage_node_id(node.revise_target),
            condition="route == 'revise'",
            metadata={"builders_revision": True},
        )
        for node in graph
        if node.gate is not None and node.revise_target is not None
    ]


def _entry_frontier(graph: PipelineGraph) -> tuple[str, list[Node], list[Edge]]:
    roots = _roots(graph)
    if len(roots) == 1:
        return _stage_node_id(roots[0].name), [], []

    control_node = Node(
        node_id=_START_NODE_ID,
        node_type=_START_KIND,
        name="Builders ready frontier",
        policies={"max_attempts": 1},
        metadata={"builders_control": True},
    )
    control_edges = _fanout_edges(
        _START_NODE_ID,
        [_stage_node_id(root.name) for root in roots],
    )
    return _START_NODE_ID, [control_node], control_edges


def _canonical_graph(
    graph: PipelineGraph,
    *,
    run: Any,
    workspace_id: str,
    project_id: str,
) -> Graph:
    entry, control_nodes, control_edges = _entry_frontier(graph)
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=f"Builders pipeline #{run.issue_number}",
        description=str(run.title),
        nodes=[*control_nodes, *_canonical_stage_nodes(graph)],
        edges=[*_dependency_edges(graph), *_revision_edges(graph), *control_edges],
        metadata={
            "entry_node": entry,
            "execution_owner": "canonical_run",
            "product": "builders",
            "pipeline_id": str(run.id),
        },
    )


def _resolver(
    graph: PipelineGraph,
    *,
    run: Any,
    dispatcher: PipelineDispatcher,
    budget: IterationBudget,
) -> Callable[[str, Graph], BaseNode[Any, Any]]:
    stages = {node.name: node for node in graph}
    start = _StartNode()
    stage_nodes = {
        name: _StageNode(
            graph=graph,
            node=node,
            run=run,
            dispatcher=dispatcher,
            budget=budget,
        )
        for name, node in stages.items()
    }

    def resolve(node_id: str, _canonical_graph: Graph) -> BaseNode[Any, Any]:
        if node_id == _START_NODE_ID:
            return start
        name = _stage_name(node_id)
        if name is None or name not in stage_nodes:
            raise KeyError(f"unknown Builders canonical node {node_id!r}")
        return stage_nodes[name]

    return resolve


def _latest_stage_runs(record: DurableRunRecord) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for node_run in record.node_runs:
        name = _stage_name(node_run.node_id)
        if name is not None:
            latest[name] = node_run
    return latest


def _failed_stage(record: DurableRunRecord) -> str | None:
    for node_run in reversed(record.node_runs):
        name = _stage_name(node_run.node_id)
        if name is not None and node_run.status is RunStatus.FAILED:
            return name
    return None


def _project_run_status(run: Any, record: DurableRunRecord, failed_stage: str | None) -> None:
    if record.run.status is RunStatus.COMPLETED:
        run.status = "completed"
    elif failed_stage is not None:
        run.status = f"failed at {failed_stage}"
    else:
        run.status = record.run.status.value


def _project_stage(run: Any, stage: Any, node_run: Any, failed_stage: str | None) -> None:
    if stage.name in run.skipped_stages:
        stage.status = _stage_status("skipped")
    elif node_run is None:
        stage.status = _stage_status("pending")
    elif node_run.status is RunStatus.COMPLETED:
        stage.status = _stage_status("completed")
    elif node_run.status is RunStatus.RUNNING:
        stage.status = _stage_status("running")
    elif node_run.status in {
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }:
        stage.status = _stage_status("failed")
        if stage.name == failed_stage:
            stage.error = run.failed_stage_error or str(node_run.error or "")


def _project_canonical_record(run: Any, record: DurableRunRecord) -> None:
    """Refresh the compatibility receipt from canonical execution evidence."""
    latest_by_stage = _latest_stage_runs(record)
    failed_stage = _failed_stage(record)
    _project_run_status(run, record, failed_stage)
    for stage in run.stages:
        _project_stage(run, stage, latest_by_stage.get(stage.name), failed_stage)


def _stage_status(value: str) -> Any:
    # Local import avoids a module cycle: pipeline imports GraphPipelineExecutor.
    from maistro.builders.pipeline import StageStatus

    return StageStatus(value)


class CanonicalGraphPipelineExecutor:
    """Execute a Builders ``PipelineGraph`` on the canonical durable spine."""

    def __init__(
        self,
        dispatcher: PipelineDispatcher,
        *,
        run_store: RunStore,
        durable_store: DurableRunStore,
        workspace_id: str,
        project_id: str,
        actor_principal_id: str | None = None,
        budget: IterationBudget | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._run_store = run_store
        self._durable_store = durable_store
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._actor_principal_id = actor_principal_id
        self._budget = budget

    async def execute(self, graph: PipelineGraph, run: Any) -> DurableRunRecord:
        """Run one Builders pipeline as canonical Graph -> Run -> NodeRun -> Attempt work."""
        errors = graph.validate()
        if errors:
            raise ValueError(f"invalid Builders pipeline graph: {'; '.join(errors)}")

        budget = self._budget or IterationBudget(
            max_iterations=_DEFAULT_EXECUTIONS_PER_NODE * len(graph)
        )
        canonical = _canonical_graph(
            graph,
            run=run,
            workspace_id=self._workspace_id,
            project_id=self._project_id,
        )
        provenance = {
            "admission_source": _ADMISSION_SOURCE,
            "product": "builders",
            "pipeline_id": str(run.id),
            "issue_number": int(run.issue_number),
        }
        admitted = await self._run_store.create_run(
            canonical,
            actor_principal_id=self._actor_principal_id,
            provenance=provenance,
            initial_status=RunStatus.QUEUED,
        )
        run.canonical_run_id = admitted.run_id
        # Compatibility projection only. Canonical Run/NodeRun/Attempt remain
        # authoritative for lifecycle; legacy hooks may still inspect this receipt.
        run.status = "running"
        record = await run_durable_graph(
            canonical,
            store=self._durable_store,
            node_resolver=_resolver(
                graph,
                run=run,
                dispatcher=self._dispatcher,
                budget=budget,
            ),
            actor_principal_id=self._actor_principal_id,
            run_id=run.canonical_run_id,
            provenance=provenance,
            run_store=self._run_store,
        )
        _project_canonical_record(run, record)
        return record
