"""Canonical Run inspection/control composition for the Conductor (#1036)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.runs.model import AttemptStatus, NodeRun, Run, RunStatus


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


async def _allowed() -> set[str]:
    return {"workspace-1"}
