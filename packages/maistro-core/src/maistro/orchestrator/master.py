"""Master Orchestrator compatibility API over canonical Graph execution.

The planner-facing WorkItem/Wave shapes remain useful domain projections, but
physical execution belongs to Graph -> Run -> NodeRun -> Attempt. This module
translates loaded waves into Graph structure and projects canonical execution
back onto WorkItems instead of maintaining a second execution lifecycle.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import TypeAdapter

from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
)
from maistro.graph.durable_runs.attempt_executor import run_durable_graph
from maistro.graph.durable_runs.executor import MAX_NODE_VISITS
from maistro.graph.durable_runs.protocol import DurableRunStore
from maistro.graph.nodes.base import NodeContext, NodeResult
from maistro.projects.scope_store import InMemoryProjectScopeStore, ProjectScopeStore
from maistro.runs.lifecycle import latest_node_runs
from maistro.runs.model import NodeRun, RunStatus
from maistro.runs.store import InMemoryRunStore, RunStore
from maistro.runtime import PythonExecutionRuntime

logger = logging.getLogger("maistro.orchestrator")

_ROOT_NODE_ID = "__master_orchestrator_root__"
_OUTCOME_PREFIX = "orchestrator_outcome__"
_RESULT_MAPPING = TypeAdapter(dict[str, Any])


class WorkItemStatus:
    """Compatibility vocabulary projected from canonical NodeRun result payloads."""

    PENDING: ClassVar[str] = "pending"
    IN_PROGRESS: ClassVar[str] = "in_progress"
    PASSED: ClassVar[str] = "passed"
    FAILED: ClassVar[str] = "failed"
    BLOCKED: ClassVar[str] = "blocked"
    SKIPPED: ClassVar[str] = "skipped"


@dataclass
class WorkItem:
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    group: str = ""
    task_id: str = ""
    description: str = ""
    agent_role: str = "mason"
    depends_on: list[str] = field(default_factory=list)
    status: str = WorkItemStatus.PENDING
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


def _outcome_key(task_id: str) -> str:
    return f"{_OUTCOME_PREFIX}{task_id}"


class _RootNode:
    kind = "orchestrator.root"

    async def run(self, inputs: Any, ctx: NodeContext) -> NodeResult:
        del inputs, ctx
        return NodeResult(success=True, status="completed", output={"ready": True})


class _WorkItemNode:
    kind = "orchestrator.work_item"

    def __init__(
        self,
        *,
        item: WorkItem,
        handler: StageHandler | None,
        security_gate: StageHandler | None,
    ) -> None:
        self._item = item
        self._handler = handler
        self._security_gate = security_gate

    def _output(
        self,
        status: str,
        message: str,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            _outcome_key(self._item.task_id): {
                "status": status,
                "result": message,
                "metadata": dict(metadata),
            }
        }

    def _failed(
        self,
        message: str,
        *,
        error_code: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> NodeResult:
        return NodeResult(
            success=False,
            status="failed",
            error_code=error_code,
            error_message=message,
            output=self._output(WorkItemStatus.FAILED, message, metadata or {}),
        )

    def _domain_failure(
        self,
        message: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> NodeResult:
        """Represent a non-executable WorkItem failure without spending retries."""
        return NodeResult(
            success=True,
            status="completed",
            output=self._output(WorkItemStatus.FAILED, message, metadata or {}),
        )

    def _blocked_dependencies(self, inputs: Mapping[str, Any]) -> list[str]:
        blocked: list[str] = []
        for dependency in self._item.depends_on:
            value = inputs.get(_outcome_key(dependency))
            if not isinstance(value, Mapping) or value.get("status") != WorkItemStatus.PASSED:
                blocked.append(dependency)
        return blocked

    async def _run_handler(self) -> WorkItem | NodeResult:
        if self._handler is None:
            return self._domain_failure(f"No handler for agent role: {self._item.agent_role}")
        self._item.status = WorkItemStatus.IN_PROGRESS
        try:
            return await self._handler(self._item)
        except Exception as exc:
            logger.exception("Work item %s raised: %s", self._item.task_id, exc)
            return self._failed(str(exc), error_code=type(exc).__name__)

    async def _apply_security_gate(
        self,
        result: WorkItem,
    ) -> tuple[str, str, dict[str, Any]]:
        status = str(result.status)
        message = result.result
        metadata = dict(result.metadata)
        if self._security_gate is None or status != WorkItemStatus.PASSED:
            return status, message, metadata
        try:
            secured = await self._security_gate(result)
        except Exception as exc:
            logger.exception("Security gate for %s raised: %s", self._item.task_id, exc)
            return WorkItemStatus.FAILED, f"Security gate: {exc}", metadata
        metadata.update(secured.metadata)
        if secured.status == WorkItemStatus.FAILED:
            return WorkItemStatus.FAILED, f"Security gate: {secured.result}", metadata
        return status, message, metadata

    async def run(self, inputs: Any, ctx: NodeContext) -> NodeResult:
        del ctx
        resolved_inputs = inputs if isinstance(inputs, Mapping) else {}
        blocked = self._blocked_dependencies(resolved_inputs)
        if blocked:
            message = f"Dependencies not met: {blocked}"
            return NodeResult(
                success=True,
                status="completed",
                output=self._output(WorkItemStatus.BLOCKED, message, {}),
            )

        handled = await self._run_handler()
        if isinstance(handled, NodeResult):
            return handled
        status, message, metadata = await self._apply_security_gate(handled)
        succeeded = status == WorkItemStatus.PASSED
        return NodeResult(
            success=succeeded,
            status="completed" if succeeded else "failed",
            error_code=None if succeeded else "WorkItemFailed",
            error_message=(
                None if succeeded else (message or f"work item {self._item.task_id} failed")
            ),
            output=self._output(status, message, metadata),
        )


class MasterOrchestrator:
    """Project a ConsolidationPlan onto the canonical execution spine."""

    def __init__(
        self,
        *,
        max_concurrent_per_wave: int = 5,
        max_retries: int = 2,
        security_gate: StageHandler | None = None,
        run_store: RunStore | None = None,
        durable_store: DurableRunStore | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        if max_concurrent_per_wave <= 0:
            raise ValueError("max_concurrent_per_wave must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if run_store is not None and (not workspace_id or not project_id):
            raise ValueError("injected run_store requires workspace_id and project_id")

        self._handlers: dict[str, StageHandler] = {}
        self._max_concurrent = max_concurrent_per_wave
        self._max_attempts = min(max_retries + 1, MAX_NODE_VISITS)
        self._security_gate = security_gate
        self._items: dict[str, WorkItem] = {}
        self._waves: list[Wave] = []
        self._xp_earned: dict[str, int] = {}
        self._workspace_id = workspace_id or f"master-{uuid4().hex}"
        self._project_id = project_id
        self._project_store: ProjectScopeStore | None = None
        if run_store is None:
            project_store = InMemoryProjectScopeStore()
            self._project_store = project_store
            run_store = InMemoryRunStore(project_store=project_store)
        self._run_store = run_store
        self._durable_store = durable_store or CanonicalDurableRunStore(
            run_store,
            InMemoryGraphContinuationStore(),
        )
        self._last_run_id: str | None = None

    @property
    def last_run_id(self) -> str | None:
        """Canonical Run id produced by the most recent execute call."""
        return self._last_run_id

    def register_handler(self, agent_role: str, handler: StageHandler) -> None:
        self._handlers[agent_role] = handler

    def load_plan(self, waves: list[list[WorkItem]]) -> None:
        task_ids = [item.task_id for wave in waves for item in wave]
        if any(not task_id for task_id in task_ids):
            raise ValueError("every WorkItem requires a task_id")
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("WorkItem task_id values must be unique")
        if _ROOT_NODE_ID in task_ids:
            raise ValueError(f"task_id {_ROOT_NODE_ID!r} is reserved")
        self._waves = [Wave(wave_number=i, items=items) for i, items in enumerate(waves)]
        self._items = {item.task_id: item for wave in self._waves for item in wave.items}

    def _nonempty_waves(self) -> list[list[WorkItem]]:
        return [wave.items for wave in self._waves if wave.items]

    def _graph_nodes(self) -> list[Node]:
        nodes = [
            Node(
                node_id=_ROOT_NODE_ID,
                node_type="orchestrator.root",
                name="Master Orchestrator root",
            )
        ]
        nodes.extend(
            Node(
                node_id=item.task_id,
                node_type="orchestrator.work_item",
                name=item.description or item.task_id,
                policies={
                    "max_attempts": self._max_attempts,
                    "continue_on_failure": True,
                },
                metadata={"agent_role": item.agent_role, "group": item.group},
            )
            for item in self._items.values()
        )
        return nodes

    def _wave_edges(self) -> list[Edge]:
        waves = self._nonempty_waves()
        if not waves:
            return []
        edges = [
            Edge(
                from_node=_ROOT_NODE_ID,
                to_node=item.task_id,
                metadata={"kind": "wave", "parallel": True},
            )
            for item in waves[0]
        ]
        for previous, current in pairwise(waves):
            edges.extend(
                Edge(
                    from_node=source.task_id,
                    to_node=target.task_id,
                    metadata={"kind": "wave", "parallel": True},
                )
                for source in previous
                for target in current
            )
        return edges

    def _dependency_edges(self) -> list[Edge]:
        edges: list[Edge] = []
        for item in self._items.values():
            for dependency in item.depends_on:
                if dependency not in self._items:
                    raise ValueError(
                        f"WorkItem {item.task_id!r} depends on unknown task {dependency!r}"
                    )
                edges.append(
                    Edge(
                        from_node=dependency,
                        to_node=item.task_id,
                        metadata={"kind": "dependency", "parallel": True},
                    )
                )
        return edges

    @staticmethod
    def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
        by_pair: dict[tuple[str, str], Edge] = {}
        for edge in edges:
            by_pair.setdefault((edge.from_node, edge.to_node), edge)
        return list(by_pair.values())

    def _graph_edges(self) -> list[Edge]:
        return self._dedupe_edges([*self._wave_edges(), *self._dependency_edges()])

    def _build_graph(self, *, project_id: str) -> Graph:
        return Graph(
            workspace_id=self._workspace_id,
            project_id=project_id,
            name="Master Orchestrator plan",
            nodes=self._graph_nodes(),
            edges=self._graph_edges(),
            metadata={
                "source": "master_orchestrator",
                "max_frontier_concurrency": self._max_concurrent,
            },
        )

    def _resolve_node(self, node_id: str, graph: Graph) -> Any:
        del graph
        if node_id == _ROOT_NODE_ID:
            return _RootNode()
        item = self._items[node_id]
        return _WorkItemNode(
            item=item,
            handler=self._handlers.get(item.agent_role),
            security_gate=self._security_gate,
        )

    async def _scope_project_id(self) -> str:
        if self._project_id is not None:
            return self._project_id
        if self._project_store is None:
            raise RuntimeError("canonical Project scope is unavailable")
        root = await self._project_store.create_root(self._workspace_id)
        self._project_id = root.project_id
        return root.project_id

    @staticmethod
    def _projection_payload(
        node_run: NodeRun,
    ) -> tuple[str, str, dict[str, Any]] | None:
        if not isinstance(node_run.result, dict):
            return None
        result = _RESULT_MAPPING.validate_python(node_run.result)
        raw = result.get(_outcome_key(node_run.node_id))
        if not isinstance(raw, Mapping):
            return None
        status = raw.get("status")
        message = raw.get("result", "")
        metadata = raw.get("metadata", {})
        if (
            not isinstance(status, str)
            or not isinstance(message, str)
            or not isinstance(metadata, dict)
        ):
            return None
        return status, message, dict(metadata)

    def _project_one(self, item: WorkItem, node_run: NodeRun | None) -> None:
        if node_run is None:
            item.status = WorkItemStatus.SKIPPED
            return

        item.started_at = node_run.started_at
        item.completed_at = node_run.finished_at
        payload = self._projection_payload(node_run)
        if node_run.status is RunStatus.COMPLETED:
            item.status = payload[0] if payload is not None else WorkItemStatus.PASSED
            if payload is not None:
                _, item.result, metadata = payload
                item.metadata.update(metadata)
            return
        if node_run.status in {
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
        }:
            item.status = WorkItemStatus.FAILED
            item.result = node_run.error or "failed"
            return
        if node_run.status in {RunStatus.RUNNING, RunStatus.WAITING, RunStatus.PAUSED}:
            item.status = WorkItemStatus.IN_PROGRESS
        else:
            item.status = WorkItemStatus.PENDING

    def _project_xp(self) -> None:
        totals: dict[str, int] = {}
        for item in self._items.values():
            if item.status == WorkItemStatus.PASSED:
                xp = item.metadata.get("xp_earned", 10)
                if isinstance(xp, int):
                    totals[item.agent_role] = totals.get(item.agent_role, 0) + xp
        self._xp_earned = totals

    def _project_waves(self) -> None:
        now = datetime.now(UTC)
        terminal = {
            WorkItemStatus.PASSED,
            WorkItemStatus.FAILED,
            WorkItemStatus.BLOCKED,
            WorkItemStatus.SKIPPED,
        }
        for wave in sorted(self._waves, key=lambda candidate: candidate.wave_number):
            starts = [item.started_at for item in wave.items if item.started_at is not None]
            if starts:
                wave.started_at = min(starts)
            if all(item.status in terminal for item in wave.items):
                wave.completed_at = max(
                    (item.completed_at for item in wave.items if item.completed_at is not None),
                    default=now,
                )

    def _project_items(self, node_runs: list[NodeRun]) -> None:
        newest = latest_node_runs(node_runs)
        for item in self._items.values():
            self._project_one(item, newest.get(item.task_id))
        self._project_xp()
        self._project_waves()

    async def execute(self) -> OrchestratorResult:
        started = datetime.now(UTC)
        project_id = await self._scope_project_id()
        graph = self._build_graph(project_id=project_id)
        admitted = await self._run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            provenance={"admission_source": "master_orchestrator"},
        )
        self._last_run_id = admitted.run_id
        record = await run_durable_graph(
            graph,
            store=self._durable_store,
            node_resolver=self._resolve_node,
            run_id=admitted.run_id,
            runtime=PythonExecutionRuntime(max_concurrency=self._max_concurrent),
            run_store=self._run_store,
        )
        self._project_items(list(record.node_runs))

        duration = (datetime.now(UTC) - started).total_seconds()
        total = len(self._items)
        completed = sum(1 for item in self._items.values() if item.status == WorkItemStatus.PASSED)
        failed = sum(1 for item in self._items.values() if item.status == WorkItemStatus.FAILED)
        summary = OrchestratorResult(
            plan_id=record.run_id,
            total_items=total,
            completed=completed,
            failed=failed,
            skipped=total - completed - failed,
            waves_total=len(self._waves),
            waves_completed=sum(1 for wave in self._waves if wave.completed_at is not None),
            duration_seconds=duration,
        )
        logger.debug("MasterOrchestrator canonical Run %s finished", summary.plan_id)
        return summary

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
