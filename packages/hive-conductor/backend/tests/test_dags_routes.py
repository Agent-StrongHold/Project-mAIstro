"""Route coverage for the Conductor DAG CRUD and canonical Run projection."""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _seed(client: Any) -> str:
    response = client.post("/v1/dags", json={"name": "seed", "description": ""})
    assert response.status_code == 201
    return response.json()["id"]


def test_list_dags_returns_array(admin_client: Any) -> None:
    response = admin_client.get("/v1/dags")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_dag_by_id_returns_payload(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    response = admin_client.get(f"/v1/dags/{dag_id}")
    assert response.status_code == 200
    assert response.json()["id"] == dag_id
    assert response.json()["name"] == "seed"


def test_get_dag_missing_returns_404(admin_client: Any) -> None:
    assert admin_client.get("/v1/dags/missing-xyz").status_code == 404


def test_add_and_remove_node(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    response = admin_client.post(
        f"/v1/dags/{dag_id}/nodes",
        json={"role": "scout", "name": "Scout"},
    )
    assert response.status_code == 200
    node_id = response.json()["id"]
    assert response.json()["role"] == "scout"

    removed = admin_client.delete(f"/v1/dags/{dag_id}/nodes/{node_id}")
    assert removed.status_code == 200
    assert removed.json()["id"] == node_id


def test_add_node_dag_404(admin_client: Any) -> None:
    response = admin_client.post(
        "/v1/dags/missing-dag/nodes",
        json={"role": "scout", "name": "x"},
    )
    assert response.status_code == 404


def test_remove_node_dag_404(admin_client: Any) -> None:
    assert admin_client.delete("/v1/dags/missing-dag/nodes/any").status_code == 404


def test_remove_node_not_found(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    assert admin_client.delete(f"/v1/dags/{dag_id}/nodes/no-such").status_code == 404


def test_add_and_remove_edge(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    current = admin_client.get(f"/v1/dags/{dag_id}").json()
    src = current["nodes"][0]["id"]
    dst = current["nodes"][1]["id"]
    response = admin_client.post(
        f"/v1/dags/{dag_id}/edges",
        json={"from_node": src, "to_node": dst, "condition": "if x"},
    )
    assert response.status_code == 200
    edge_id = response.json()["id"]
    assert response.json()["condition"] == "if x"

    removed = admin_client.delete(f"/v1/dags/{dag_id}/edges/{edge_id}")
    assert removed.status_code == 200
    assert removed.json()["id"] == edge_id


def test_add_edge_dag_404(admin_client: Any) -> None:
    response = admin_client.post(
        "/v1/dags/missing/edges",
        json={"from_node": "a", "to_node": "b"},
    )
    assert response.status_code == 404


def test_remove_edge_dag_404(admin_client: Any) -> None:
    assert admin_client.delete("/v1/dags/missing/edges/any").status_code == 404


def test_remove_edge_not_found(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    assert admin_client.delete(f"/v1/dags/{dag_id}/edges/no-such").status_code == 404


def test_delete_dag_succeeds_and_then_404s(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    assert admin_client.delete(f"/v1/dags/{dag_id}").status_code == 204
    assert admin_client.get(f"/v1/dags/{dag_id}").status_code == 404


def test_delete_dag_missing_returns_404(admin_client: Any) -> None:
    assert admin_client.delete("/v1/dags/never-existed").status_code == 404


def test_activate_dag(admin_client: Any) -> None:
    import stores

    before_audit = len(stores.audit_log)
    dag_id = _seed(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/activate")
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    entries = list(stores.audit_log.values())
    assert any(
        entry["action"] == "dag_activate" and entry["target"] == dag_id
        for entry in entries[before_audit:]
    )


def test_activate_dag_missing_404(admin_client: Any) -> None:
    assert admin_client.post("/v1/dags/missing-dag/activate").status_code == 404


def _canonical_container(monkeypatch: pytest.MonkeyPatch, workspace_id: str) -> Any:
    from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore

    projects = InMemoryProjectScopeStore()
    asyncio.run(projects.create_root(workspace_id))
    run_store = InMemoryRunStore(project_store=projects)
    container = SimpleNamespace(
        config=SimpleNamespace(workspace_id=workspace_id),
        project_scope_store=projects,
        run_store=run_store,
        graph_run_store=CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore()),
        a2a_delegator=None,
        guest_peers=None,
    )
    import services.engine as engine

    monkeypatch.setattr(
        engine,
        "get_engine",
        lambda: SimpleNamespace(_agent_port=SimpleNamespace(container=container)),
    )
    return container


def _route_dag(dag_id: str, *, kind: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": dag_id,
        "name": dag_id,
        "description": "route integration",
        "workspace_id": "route-workspace",
        "nodes": [{"id": "n1", "kind": kind, "config": config or {}, "inputs": {}}],
        "edges": [],
        "entry_node": "n1",
    }


def _install_route_workspace(workspace_id: str, user_id: str) -> None:
    import stores
    from models.workspace import Workspace, WorkspaceMember

    now = datetime.now(UTC)
    stores.workspaces[workspace_id] = Workspace(
        id=workspace_id,
        persona_template_id="pm_fleet",
        name=workspace_id,
        members=[WorkspaceMember(user_id=user_id, role="owner")],
        created_at=now,
        updated_at=now,
    )


def test_run_dag_uses_one_canonical_run_for_history_projection(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The HTTP button reaches the registered path and both stores name one Run."""
    import services.graph_runner as graph_runner
    import stores
    from services.dag_run_store import get_dag_run_store

    workspace_id = "route-workspace"
    dag_id = "route-canonical-success"
    container = _canonical_container(monkeypatch, workspace_id)
    _install_route_workspace(workspace_id, "admin")
    stores.dags[dag_id] = _route_dag(dag_id, kind="transform.alias_keys")

    async def legacy_path_must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the DAG route must not call graph_runner.execute_dag")

    monkeypatch.setattr(graph_runner, "execute_dag", legacy_path_must_not_run)
    response = admin_client.post(f"/v1/dags/{dag_id}/run?workspace_id={workspace_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"

    run_id = body["run_id"]
    canonical = asyncio.run(container.run_store.get_run(run_id))
    projection = get_dag_run_store().get_run(run_id)
    assert canonical is not None
    assert canonical.run_id == run_id
    assert canonical.status.value == "completed"
    assert projection is not None
    assert projection["canonical_run_id"] == canonical.run_id
    assert projection["status"] == canonical.status.value
    assert projection["event_count"] == 1


def test_run_dag_cannot_project_a_failed_canonical_node_as_completed(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stores
    from services.dag_run_store import get_dag_run_store

    workspace_id = "route-workspace"
    dag_id = "route-canonical-failure"
    container = _canonical_container(monkeypatch, workspace_id)
    _install_route_workspace(workspace_id, "admin")
    # An empty Jira base URL makes the canonical node fail during execution,
    # after the durable executor has created its NodeRun.
    stores.dags[dag_id] = _route_dag(dag_id, kind="jira.poll")

    response = admin_client.post(f"/v1/dags/{dag_id}/run?workspace_id={workspace_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    run_id = body["run_id"]

    canonical = asyncio.run(container.run_store.get_run(run_id))
    projection = get_dag_run_store().get_run(run_id)
    assert canonical is not None
    assert canonical.status.value == "failed"
    node_runs = asyncio.run(container.run_store.list_node_runs(run_id))
    # Terminal Run reconciliation settles the open NodeRun as cancelled after
    # the node failure; the Run's failed status remains the lifecycle authority.
    assert [node_run.status.value for node_run in node_runs] == ["cancelled"]
    assert projection is not None
    assert projection["canonical_run_id"] == run_id
    assert projection["status"] == "failed"
    assert projection["node_states"], projection
    assert all(state != "completed" for state in projection["node_states"].values())


@pytest.mark.asyncio
async def test_projection_preserves_a_waiting_canonical_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import routes.dags as dags_routes
    from services.dag_run_store import DagRunStore

    store = DagRunStore()
    # The route's helper imports the accessor lazily, so patch the module that
    # owns that seam rather than creating a second projection implementation.
    import services.dag_run_store as history

    monkeypatch.setattr(history, "get_dag_run_store", lambda: store)
    await dags_routes._record_run_projection(
        dag_id="dag-waiting",
        user_id="admin",
        result={
            "status": "waiting",
            "run_id": "run-waiting",
            "workspace_id": "ws-waiting",
            "project_id": "project-waiting",
            "node_results": {"n1": {"role": "worker", "success": False}},
        },
    )

    projection = store.get_run("run-waiting")
    assert projection is not None
    assert projection["status"] == "waiting"
    assert projection["node_states"]["worker.n1"] == "running"


def test_run_dag_missing_dag_returns_404(admin_client: Any) -> None:
    assert admin_client.post("/v1/dags/missing-dag/run").status_code == 404


def test_run_champion_success_uses_canonical_run_id(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    async def ok() -> dict[str, Any]:
        return {"status": "completed", "run_id": "champion-run", "champion": True}

    monkeypatch.setattr(graph_runner, "execute_champion", ok)
    response = admin_client.post("/v1/dags/run-champion")
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["champion"] is True
    assert body["execution_id"] == "champion-run"
    assert body["run_id"] == "champion-run"


def test_run_champion_failure(admin_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.graph_runner as graph_runner

    async def boom() -> dict[str, Any]:
        raise RuntimeError("champion crash")

    monkeypatch.setattr(graph_runner, "execute_champion", boom)
    response = admin_client.post("/v1/dags/run-champion")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "champion crash" in body["error"]


@pytest.mark.asyncio
async def test_a_result_without_a_run_id_projects_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Recent Runs projection keys on the canonical Run id; a result that
    never got one (pre-admission failure shapes) must not mint a projection
    row under some synthesized key."""
    import routes.dags as dags_routes
    import services.dag_run_store as history

    def _unexpected_store() -> Any:  # pragma: no cover
        raise AssertionError("no store may be consulted without a run id")

    monkeypatch.setattr(history, "get_dag_run_store", _unexpected_store)

    await dags_routes._record_run_projection(
        dag_id="dag-1",
        user_id="admin",
        result={"status": "failed", "error": "no run was admitted"},
    )
