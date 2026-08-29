"""Master Orchestrator projection over canonical durable Graph execution.

The planner-facing WorkItem/Wave shapes remain useful product projections, but
physical execution belongs to Graph -> Run -> NodeRun -> Attempt. Master no
longer owns a competing retry loop, dependency gate, semaphore executor, or
terminal-status enum.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal
from uuid import uuid4

from pydantic import BaseModel

from maistro.graph.definitions import Edge, Graph, Node as GraphNode
from maistro.graph.durable_runs import DurableRunStore, InMemoryDurableRunStore, run_durable_graph
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.runs.model import RunStatus

WorkItemProjectionStatus = Literal[
    "pending",
    "in_progress",
    "passed",
    "failed",
    "blocked",
    "skipped",
]


@dataclass
class WorkItem:
    """Planner-facing work description plus a projection of canonical execution."""

    id: str = field(default_factory=lambda: uuid4().hex[:8])
    group: str = ""
    task_id: str = ""
    description: str = ""
    agent_role: str = "mason"
    depends_on: list[str] = field(default_factory=list)
    status: WorkItemProjectionStatus = "pending"
    result: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Wave:
    wave_number: int
    items: list[WorkItem] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class OrchestratorResult:
    plan_id: str
    total_items: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    waves_total: int = 0
    waves_completed: int = 0
    duration_seconds: float = 0.0


StageHandler = Callable[[WorkItem], Coroutine[Any, Any, WorkItem]]


class _HandlerInput(BaseModel):
    pass


class _HandlerOutput(BaseModel):
    result: str = ""
    metadata: dict[str, Any] = {}


class _HandlerNode(BaseNode[_HandlerInput, _HandlerOutput]):
    """Adapt one legacy stage handler to the canonical Graph node contract.

    A handler may still report ``status='failed'`` as its domain outcome signal,
    but that value is never persisted as execution truth. The Graph executor
    converts the signal into a failed NodeResult, and canonical NodeRun/Attempt
    records own the lifecycle from there.
    """

    kind: ClassVar[str] = "orchestrator.work_item"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _HandlerInput
    output_schema: ClassVar[type[BaseModel]] = _HandlerOutput

    def __init__(
        self,
        item: WorkItem,
        handler: StageHandler,
        security_gate: StageHandler | None,
    ) -> None:
        self._item = item
        self._handler = handler
        self._security_gate = security_gate

    async def _execute(self, inputs: _HandlerInput, ctx: NodeContext) -> _HandlerOutput:
        del inputs, ctx
        working = replace(
            self._item,
            depends_on=list(self._item.depends_on),
            metadata=dict(self._item.metadata),
            status="pending",
            result="",
            started_at=None,
            completed_at=None,
        )
        outcome = await self._handler(working)
        if outcome.status == "failed":
            raise RuntimeError(outcome.result or f"work item {outcome.task_id!r} failed")

        if self._security_gate is not None:
            checked = await self._security_gate(outcome)
            if checked.status == "failed":
                raise RuntimeError(f"Security gate: {checked.result}")
            outcome = checked

        return _HandlerOutput(result=outcome.result, metadata=dict(outcome.metadata))


class _RootNode(BaseNode[_HandlerInput, _HandlerOutput]):
    """Synthetic Graph entry used to fan out all dependency-free work."""

    kind: ClassVar[str] = "orchestrator.root"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _HandlerInput
    output_schema: ClassVar[type[BaseModel]] = _HandlerOutput

    async def _execute(self, inputs: _HandlerInput, ctx: NodeContext) -> _HandlerOutput:
        del inputs, ctx
        return _HandlerOutput()


class MasterOrchestrator:
    """Project planner work onto the canonical durable execution spine.

    WorkItem and Wave remain presentation/domain shapes. Dependencies become
    Graph edges, concurrent work is the active Graph frontier, retry budgets are
    node visit policies, and physical tries are Attempts.
    """

    _ROOT_NODE_ID = "__master_orchestrator_root__"

    def __init__(
        self,
        *,
        max_concurrent_per_wave: int = 5,
        max_retries: int = 2,
        security_gate: StageHandler | None = None,
        durable_store: DurableRunStore | None = None,
        workspace_id: str = "master-orchestrator",
        project_id: str = "master-orchestrator",
    ) -> None:
        # Retained as a compatibility hint only. Canonical Graph frontier
        # execution owns concurrency; Master must not wrap it in a semaphore.
        self._max_concurrent = max_concurrent_per_wave
        self._max_retries = max(0, max_retries)
        self._security_gate = security_gate
        self._durable_store = durable_store or InMemoryDurableRunStore()
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._handlers: dict[str, StageHandler] = {}
        self._items: dict[str, WorkItem] = {}
        self._waves: list[Wave] = []
        self._xp_earned: dict[str, int] = {}
        self._nodes: dict[str, BaseNode[Any, Any]] = {}

    def register_handler(self, agent_role: str, handler: StageHandler) -> None:
        self._handlers[agent_role] = handler

    def load_plan(self, waves: list[list[WorkItem]]) -> None:
        self._waves = [Wave(wave_number=i, items=items) for i, items in enumerate(waves)]
        self._items = {item.task_id: item for wave in self._waves for item in wave.items}

    def _build_graph(self) -> Graph:
        nodes = [
            GraphNode(node_id=self._ROOT_NODE_ID, node_type=_RootNode.kind, name="orchestrator entry")
        ]
        edges: list[Edge] = []
        for item in self._items.values():
            nodes.append(
                GraphNode(
                    node_id=item.task_id,
                    node_type=_HandlerNode.kind,
                    name=item.description or item.task_id,
                    policies={"max_attempts": self._max_retries + 1},
                    metadata={
                        "agent_role": item.agent_role,
                        "work_item_id": item.id,
                        "group": item.group,
                    },
                )
            )
            if item.depends_on:
                edges.extend(Edge(from_node=dep, to_node=item.task_id) for dep in item.depends_on)
            else:
                edges.append(Edge(from_node=self._ROOT_NODE_ID, to_node=item.task_id))

        return Graph(
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            name="master-orchestrator-plan",
            nodes=nodes,
            edges=edges,
            metadata={"entry_node": self._ROOT_NODE_ID},
        )

    def _prepare_nodes(self) -> None:
        self._nodes = {self._ROOT_NODE_ID: _RootNode()}
        for item in self._items.values():
            handler = self._handlers.get(item.agent_role)
            if handler is None:
                async def _missing(_: WorkItem, *, role: str = item.agent_role) -> WorkItem:
                    raise RuntimeError(f"No handler for agent role: {role}")

                handler = _missing
            self._nodes[item.task_id] = _HandlerNode(item, handler, self._security_gate)

    def _resolve_node(self, node_id: str, graph: Graph) -> BaseNode[Any, Any]:
        del graph
        return self._nodes[node_id]

    @staticmethod
    def _project_payload(item: WorkItem, result: object | None) -> None:
        if not isinstance(result, Mapping):
            return
        value = result.get("result")
        if isinstance(value, str):
            item.result = value
        metadata = result.get("metadata")
        if isinstance(metadata, Mapping):
            item.metadata.update({str(key): value for key, value in metadata.items()})

    def _project_record(self, record: Any) -> None:
        latest = {
            node_run.node_id: node_run
            for node_run in record.node_runs
            if node_run.node_id != self._ROOT_NODE_ID
        }
        for item in self._items.values():
            node_run = latest.get(item.task_id)
            if node_run is None:
                dep_statuses = [self._items[dep].status for dep in item.depends_on if dep in self._items]
                item.status = "blocked" if any(s in {"failed", "blocked"} for s in dep_statuses) else "skipped"
                continue
            if node_run.status is RunStatus.COMPLETED:
                item.status = "passed"
                self._project_payload(item, node_run.result)
                xp = item.metadata.get("xp_earned", 10)
                if isinstance(xp, int):
                    self._xp_earned[item.agent_role] = self._xp_earned.get(item.agent_role, 0) + xp
            elif node_run.status is RunStatus.FAILED:
                item.status = "failed"
                item.result = node_run.error or item.result
            elif node_run.status is RunStatus.RUNNING:
                item.status = "in_progress"
            else:
                item.status = "pending"
            item.started_at = getattr(node_run, "started_at", None)
            item.completed_at = getattr(node_run, "finished_at", None)

        for wave in self._waves:
            timestamps = [item.started_at for item in wave.items if item.started_at is not None]
            completed = [item.completed_at for item in wave.items if item.completed_at is not None]
            wave.started_at = min(timestamps) if timestamps else None
            if wave.items and all(item.status in {"passed", "failed", "blocked", "skipped"} for item in wave.items):
                wave.completed_at = max(completed) if completed else datetime.now(UTC)

    async def execute(self) -> OrchestratorResult:
        started = datetime.now(UTC)
        self._xp_earned.clear()
        for item in self._items.values():
            item.status = "pending"
            item.result = ""
            item.started_at = None
            item.completed_at = None
        for wave in self._waves:
            wave.started_at = None
            wave.completed_at = None

        self._prepare_nodes()
        record = await run_durable_graph(
            self._build_graph(),
            store=self._durable_store,
            node_resolver=self._resolve_node,
            provenance={"admission_source": "master_orchestrator"},
        )
        self._project_record(record)

        duration = (datetime.now(UTC) - started).total_seconds()
        total = len(self._items)
        completed = sum(1 for item in self._items.values() if item.status == "passed")
        failed = sum(1 for item in self._items.values() if item.status == "failed")
        skipped = total - completed - failed
        return OrchestratorResult(
            plan_id=record.run_id,
            total_items=total,
            completed=completed,
            failed=failed,
            skipped=skipped,
            waves_total=len(self._waves),
            waves_completed=sum(1 for wave in self._waves if wave.completed_at is not None),
            duration_seconds=duration,
        )

    def get_progress(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for item in self._items.values():
            by_status[item.status] = by_status.get(item.status, 0) + 1
        return {
            "total": len(self._items),
            "by_status": by_status,
            "xp_totals": dict(self._xp_earned),
            "waves_completed": sum(1 for wave in self._waves if wave.completed_at is not None),
            "waves_total": len(self._waves),
        }
