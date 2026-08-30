"""Canonical Graph/Run execution adapter for Builders pipeline stages (#734).

Builders keeps ownership of prompts, context, skip predicates, gates, revision
feedback, hooks, and result projection. Universal execution lifecycle belongs
to the existing Run/NodeRun/Attempt spine. This adapter translates a
``PipelineGraph`` into a canonical ``Graph`` and lets the public durable Graph
executor provide frontier concurrency and physical Attempt evidence.

The legacy :class:`maistro.builders.graph_executor.GraphPipelineExecutor`
remains available as the parity oracle while the parent convergence issue
chooses product composition. This module deliberately does not modify or wrap
canonical stores, traversal, or recovery internals.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from maistro.builders.graph_executor import (
    _DEFAULT_EXECUTIONS_PER_NODE,
    _build_prompt,
)
from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import DurableRunRecord, run_durable_graph
from maistro.graph.node import IterationBudget
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.runs.model import RunStatus

if TYPE_CHECKING:
    from maistro.builders.graph import PipelineGraph, PipelineNode
    from maistro.builders.graph_executor import PipelineDispatcher
    from maistro.graph.durable_runs.protocol import DurableRunStore
    from maistro.runs.store import RunStore

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
        node = self._node
        run = self._run

        if node.skip_if is not None and node.skip_if(run.context):
            _mark_skipped(run, node.name)
            return _StageOutput(stage_name=node.name, skipped=True)

        if not self._dispatcher.supports(node.agent_name, node.name):
            _mark_skipped(run, node.name)
            return _StageOutput(stage_name=node.name, skipped=True)

        if not self._budget.consume():
            error = "iteration budget exhausted"
            run.failed_stage_error = error
            raise RuntimeError(error)

        prompt = _build_prompt(node.prompt_template, run.context)
        try:
            async with asyncio.timeout(node.timeout_seconds):
                result = await self._dispatcher.run(
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

        run.context[node.name] = result.output

        if node.on_complete is not None:
            await node.on_complete(run, result.output)

        if str(run.status).startswith("failed at "):
            raise RuntimeError(run.failed_stage_error or f"{node.name} failed")

        if node.gate is not None and not node.gate(run.context):
            decision = _gate_decision(self._graph, node, run)
            if decision.halt_error is not None:
                raise RuntimeError(decision.halt_error)
            return _StageOutput(
                stage_name=node.name,
                text=result.output,
                route=decision.route,
            )

        return _StageOutput(stage_name=node.name, text=result.output)


def _roots(graph: PipelineGraph) -> list[PipelineNode]:
    return [node for node in graph if not node.depends_on]


def _canonical_graph(
    graph: PipelineGraph,
    *,
    run: Any,
    workspace_id: str,
    project_id: str,
) -> Graph:
    nodes = [
        Node(
            node_id=_stage_node_id(node.name),
            node_type=_STAGE_KIND,
            name=node.name,
            metadata={"builders_stage": node.name},
            policies={"max_attempts": 1},
        )
        for node in graph
    ]
    edges: list[Edge] = []
    by_name = {node.name: node for node in graph}

    for node in graph:
        for dependency in node.depends_on:
            predecessor = by_name[dependency]
            edges.append(
                Edge(
                    from_node=_stage_node_id(dependency),
                    to_node=_stage_node_id(node.name),
                    condition="route == 'proceed'" if predecessor.gate is not None else None,
                )
            )

        if node.gate is not None and node.revise_target is not None:
            edges.append(
                Edge(
                    from_node=_stage_node_id(node.name),
                    to_node=_stage_node_id(node.revise_target),
                    condition="route == 'revise'",
                    metadata={"builders_revision": True},
                )
            )

    roots = _roots(graph)
    if len(roots) == 1:
        entry = _stage_node_id(roots[0].name)
    else:
        nodes.insert(
            0,
            Node(
                node_id=_START_NODE_ID,
                node_type=_START_KIND,
                name="Builders ready frontier",
                policies={"max_attempts": 1},
                metadata={"builders_control": True},
            ),
        )
        for root in roots:
            edges.append(Edge(from_node=_START_NODE_ID, to_node=_stage_node_id(root.name)))
        entry = _START_NODE_ID

    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=f"Builders pipeline #{run.issue_number}",
        description=str(run.title),
        nodes=nodes,
        edges=edges,
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
):
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


__all__ = ["CanonicalGraphPipelineExecutor"]
