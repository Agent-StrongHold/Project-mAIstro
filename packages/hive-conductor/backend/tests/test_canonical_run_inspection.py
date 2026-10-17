"""Canonical Run inspection/control composition for the Conductor (#1036)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore, RunExecutionService
from maistro.runs.model import AttemptStatus, NodeRun, Run, RunStatus
from maistro.runtime import PythonExecutionRuntime


class _CanonicalStore:
    def __init__(self, run: Run, node_run: NodeRun) -> None:
        self.run = run
        self.node_run = node_run
        self.attempt = SimpleNamespace(
            attempt_id="attempt-1",
            node_run_id=node_run.node_run_id,
            ordinal=1,
            status=AttemptStatus.COMPLETED,
            model_dump=lambda **_: {"attempt_id": "attempt-1", "node_run_id": "node-run-1"},
        )

    async def get_run(self, run_id: str) -> Run | None:
        return self.run if run_id == self.run.run_id else None

    async def list_by_status(self, status: RunStatus, *, limit: int = 100) -> list[Run]:
        return [self.run] if self.run.status is status else []

    async def list_node_runs(self, run_id: str) -> list[NodeRun]:
        return [self.node_run] if run_id == self.run.run_id else []

    async def list_attempts(self, node_run_id: str) -> list[Any]:
        return [self.attempt] if node_run_id == self.node_run.node_run_id else []

    async def transition_run(self, run_id: str, target: RunStatus, *, error: str) -> Run:
        assert run_id == self.run.run_id
        self.run = self.run.model_copy(
            update={
                "status": target,
                "finished_at": datetime.now(UTC),
                "error": error,
            }
        )
        return self.run


def _store() -> _CanonicalStore:
    graph = Graph(
        graph_id="graph-1",
        workspace_id="workspace-1",
        project_id="project-1",
        name="inspection",
        nodes=[Node(node_id="node-1", node_type="test", name="Node")],
    )
    run = Run(
        run_id="run-1",
        workspace_id="workspace-1",
        project_id="project-1",
        graph=run_graph_snapshot(graph),
        status=RunStatus.RUNNING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        provenance={"legacy_dag_id": "dag-1"},
    )
    node_run = NodeRun(
        node_run_id="node-run-1",
        run_id=run.run_id,
        node_id="node-1",
        ordinal=1,
        status=RunStatus.RUNNING,
    )
    return _CanonicalStore(run, node_run)


def run_graph_snapshot(graph: Graph) -> Any:
    from maistro.runs.model import GraphSnapshot

    return GraphSnapshot.from_graph(graph)


@pytest.mark.asyncio
async def test_detail_uses_canonical_lifecycle_and_attempt_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import dag_run_inspection as inspection

    store = _store()
    monkeypatch.setattr(inspection, "_canonical_run_store", lambda: store)
    monkeypatch.setattr(inspection, "authorized_workspace_ids", lambda _user: _allowed())

    detail = await inspection.visible_run_detail("user-1", "run-1")

    assert detail is not None
    assert detail["status"] == "running"
    assert detail["run_id"] == "run-1"
    assert detail["node_runs"][0]["node_run_id"] == "node-run-1"
    assert detail["attempts"][0]["attempt_id"] == "attempt-1"


@pytest.mark.asyncio
async def test_list_ignores_a_conflicting_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import dag_run_inspection as inspection

    store = _store()
    monkeypatch.setattr(inspection, "_canonical_run_store", lambda: store)
    monkeypatch.setattr(inspection, "authorized_workspace_ids", lambda _user: _allowed())
    monkeypatch.setattr(
        inspection,
        "get_dag_run_store",
        lambda: SimpleNamespace(list_runs=lambda **_: [{"id": "run-1", "status": "failed"}]),
    )

    listed = await inspection.list_visible_runs("user-1")

    assert listed[0]["run_id"] == "run-1"
    assert listed[0]["status"] == "running"


@pytest.mark.asyncio
async def test_cancel_transitions_the_canonical_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import dag_run_inspection as inspection

    store = _store()
    monkeypatch.setattr(inspection, "_canonical_run_store", lambda: store)
    monkeypatch.setattr(inspection, "authorized_workspace_ids", lambda _user: _allowed())

    detail = await inspection.cancel_visible_run("user-1", "run-1")

    assert detail is not None
    assert detail["status"] == "cancelled"
    assert detail["run_id"] == "run-1"
    assert detail["error"] == "cancelled by principal user-1"


@pytest.mark.asyncio
async def test_standalone_projection_is_presentation_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closeout of the ADR-082826-d9f5 standalone compatibility path.

    With no canonical bridge, the retained projection may serve reads inside
    the caller's Workspace, but it must never grant terminal authority:
    cancellation refuses rather than mutating product history.
    """
    from services import dag_run_inspection as inspection

    record = {"id": "run-1", "status": "running", "workspace_id": "workspace-1"}
    monkeypatch.setattr(inspection, "_canonical_run_store", lambda: None)
    monkeypatch.setattr(inspection, "authorized_workspace_ids", lambda _user: _allowed())
    monkeypatch.setattr(
        inspection,
        "get_dag_run_store",
        lambda: SimpleNamespace(
            get_run=lambda run_id: record if run_id == "run-1" else None,
            list_runs=lambda **_: [record],
        ),
    )

    listed = await inspection.list_visible_runs("user-1")
    assert [summary["id"] for summary in listed] == ["run-1"]
    detail = await inspection.visible_run_detail("user-1", "run-1")
    assert detail is not None
    assert detail["status"] == "running"

    # The compatibility path cannot terminalize or resurrect: no bridge means
    # no cancellation, not a projection-local one.
    assert await inspection.cancel_visible_run("user-1", "run-1") is None


@pytest.mark.asyncio
async def test_a_run_from_the_producer_seam_is_inspectable_by_canonical_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-product producer -> canonical spine -> Conductor observer.

    A Run created and executed through the real canonical producer seam
    (`RunExecutionService` over a real scoped `InMemoryRunStore` -- the same
    handoff surface Builders/schedule/Evolve adapters use) must be listable
    and inspectable by the Conductor through `dag_run_inspection` under the
    same canonical id, with NodeRun/Attempt evidence, and invisible to an
    observer outside the producing Workspace (#1036 cross-product parity).
    """
    from services import dag_run_inspection as inspection

    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    project = await project_store.create(
        workspace_id="workspace-1",
        parent_project_id=root.project_id,
        name="Cross-product",
    )
    store = InMemoryRunStore(project_store=project_store)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    graph = Graph(
        graph_id="graph-producer",
        workspace_id="workspace-1",
        project_id=project.project_id,
        name="producer",
        nodes=[Node(node_id="node-1", node_type="agent", name="Producer node")],
    )

    run = await service.create_run(graph, provenance={"producer": "non-conductor product adapter"})

    async def executor(work_item: Any, context: Any) -> dict[str, Any]:
        return {"work": work_item, "context": context}

    node_run, attempt = await service.execute_node(
        run.run_id,
        "node-1",
        "payload",
        {"run_id": run.run_id},
        executor=executor,
        executor_id="producer",
    )
    assert node_run.status is RunStatus.COMPLETED
    assert attempt.status is AttemptStatus.COMPLETED

    monkeypatch.setattr(inspection, "_canonical_run_store", lambda: store)
    monkeypatch.setattr(inspection, "authorized_workspace_ids", lambda _user: _allowed())

    listed = await inspection.list_visible_runs("user-1")
    assert [summary["run_id"] for summary in listed] == [run.run_id]

    detail = await inspection.visible_run_detail("user-1", run.run_id)
    assert detail is not None
    assert detail["canonical_run_id"] == run.run_id
    assert detail["status"] == "completed"
    assert detail["node_runs"][0]["node_run_id"] == node_run.node_run_id
    assert detail["attempts"][0]["attempt_id"] == attempt.attempt_id

    # An observer outside the producing Workspace sees nothing: cross-product
    # inspection is scoped by the canonical boundary, not by producer identity.
    monkeypatch.setattr(inspection, "authorized_workspace_ids", lambda _user: _other())
    assert await inspection.list_visible_runs("user-1") == []
    assert await inspection.visible_run_detail("user-1", run.run_id) is None


async def _allowed() -> set[str]:
    return {"workspace-1"}


async def _other() -> set[str]:
    return {"workspace-other"}
