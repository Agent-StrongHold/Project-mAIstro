"""Canonical Run inspection never trusts a stale Conductor projection."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.runs.model import RunStatus


class _Fact:
    def __init__(self, node_id: str, status: RunStatus) -> None:
        self.node_id = node_id
        self.node_run_id = f"node-run-{node_id}"
        self.status = status

    def model_dump(self, *, mode: str) -> dict[str, str]:
        del mode
        return {"node_id": self.node_id, "status": self.status.value}


class _CanonicalStore:
    def __init__(self, run: Any, node_run: _Fact) -> None:
        self.run = run
        self.node_run = node_run

    async def get_run(self, run_id: str) -> Any | None:
        return self.run if self.run.run_id == run_id else None

    async def list_node_runs(self, run_id: str) -> list[_Fact]:
        assert run_id == self.run.run_id
        return [self.node_run]

    async def list_attempts(self, node_run_id: str) -> list[Any]:
        assert node_run_id == self.node_run.node_run_id
        return []


@pytest.mark.asyncio
async def test_waiting_projection_is_not_finished_and_refresh_reads_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A waiting result remains reopenable and later canonical completion wins."""
    from services import dag_run_inspection as inspection
    from services.dag_run_store import DagRunStore

    run = SimpleNamespace(
        run_id="canonical-waiting",
        workspace_id="workspace-1",
        project_id="project-1",
        graph=SimpleNamespace(graph_id="graph-1"),
        status=RunStatus.WAITING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=None,
        result=None,
        error=None,
    )
    canonical = _CanonicalStore(run, _Fact("node-1", RunStatus.WAITING))
    history = DagRunStore()
    import services.dag_run_store as history_module
    from routes.dags import _record_run_projection

    monkeypatch.setattr(history_module, "get_dag_run_store", lambda: history)
    await _record_run_projection(
        dag_id="dag-1",
        user_id="user-1",
        result={
            "run_id": run.run_id,
            "status": "waiting",
            "workspace_id": run.workspace_id,
            "project_id": run.project_id,
            "node_results": {"node-1": {"role": "worker", "success": False, "response": "waiting"}},
        },
    )

    monkeypatch.setattr(inspection, "get_dag_run_store", lambda: history)
    monkeypatch.setattr(inspection, "_canonical_run_store", lambda: canonical)
    monkeypatch.setattr(
        inspection,
        "authorized_workspace_ids",
        lambda _user_id: asyncio.sleep(0, result={"workspace-1"}),
    )

    waiting = await inspection.visible_run_detail("user-1", run.run_id)
    assert waiting is not None
    assert waiting["status"] == "waiting"
    assert waiting["finished_at"] is None
    assert history.get_run(run.run_id)["finished_at"] is None

    run.status = RunStatus.COMPLETED
    run.finished_at = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    canonical.node_run.status = RunStatus.COMPLETED

    completed = await inspection.visible_run_detail("user-1", run.run_id)
    assert completed is not None
    assert completed["id"] == run.run_id
    assert completed["canonical_run_id"] == run.run_id
    assert completed["status"] == "completed"
    assert completed["finished_at"] == run.finished_at.timestamp()
    assert completed["node_states"] == {"node-1": "completed"}


@pytest.mark.asyncio
async def test_canonical_list_includes_runs_without_product_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inspection plane can see a canonical producer without a projection row."""
    from services import dag_run_inspection as inspection
    from services.dag_run_store import DagRunStore

    run = SimpleNamespace(
        run_id="builder-run",
        workspace_id="workspace-1",
        project_id="project-1",
        graph=SimpleNamespace(graph_id="graph-builder"),
        status=RunStatus.FAILED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        started_at=None,
        finished_at=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        result=None,
        error="builder failed",
    )
    node = _Fact("builder-node", RunStatus.FAILED)
    canonical = _CanonicalStore(run, node)

    class _ListableCanonical(_CanonicalStore):
        async def list_by_status(self, status: RunStatus, *, limit: int) -> list[Any]:
            return [self.run] if status is self.run.status else []

    canonical = _ListableCanonical(run, node)
    monkeypatch.setattr(inspection, "get_dag_run_store", DagRunStore)
    monkeypatch.setattr(inspection, "_canonical_run_store", lambda: canonical)
    monkeypatch.setattr(
        inspection,
        "authorized_workspace_ids",
        lambda _user_id: asyncio.sleep(0, result={"workspace-1"}),
    )

    rows = await inspection.list_visible_runs("user-1")
    assert rows[0]["id"] == "builder-run"
    assert rows[0]["status"] == "failed"
    assert rows[0]["canonical_run_id"] == "builder-run"
