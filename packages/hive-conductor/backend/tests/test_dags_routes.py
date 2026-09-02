"""Route coverage for the Conductor DAG CRUD and canonical Run projection."""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

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


def _completed_result(run_id: str = "run-canonical-1") -> dict[str, Any]:
    return {
        "status": "completed",
        "run_id": run_id,
        "cycles": 1,
        "node_results": {
            "n1": {
                "role": "worker",
                "success": True,
                "response": "did the thing",
                "model": "model-a",
            }
        },
        "annotations": {},
    }


def test_run_dag_success_uses_canonical_run_id(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    async def ok(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        return _completed_result()

    monkeypatch.setattr(graph_runner, "execute_dag", ok)
    dag_id = _seed(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["execution_id"] == "run-canonical-1"
    assert body["run_id"] == "run-canonical-1"
    assert body["result"]["run_id"] == "run-canonical-1"

    from services.dag_run_store import get_dag_run_store

    projection = get_dag_run_store().get_run("run-canonical-1")
    assert projection is not None
    assert projection["canonical_run_id"] == "run-canonical-1"
    assert projection["status"] == "completed"
    assert projection["event_count"] == 1


def test_run_dag_canonical_failure_stays_failed(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    failed = {
        "status": "failed",
        "run_id": "run-failed-1",
        "cycles": 1,
        "node_results": {"n1": {"role": "worker", "success": False, "response": "node failed"}},
        "error": "node failed",
    }

    async def fail(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        raise graph_runner.CanonicalDagExecutionError(failed)

    monkeypatch.setattr(graph_runner, "execute_dag", fail)
    dag_id = _seed(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["execution_id"] == "run-failed-1"
    assert body["run_id"] == "run-failed-1"
    assert "node failed" in body["error"]

    from services.dag_run_store import get_dag_run_store

    projection = get_dag_run_store().get_run("run-failed-1")
    assert projection is not None
    assert projection["canonical_run_id"] == "run-failed-1"
    assert projection["status"] == "failed"
    assert projection["node_states"]["worker.n1"] == "failed"


def test_run_dag_pre_admission_failure_has_no_fake_execution_id(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    async def boom(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ValueError("cyclic DAG rejected before execution")

    monkeypatch.setattr(graph_runner, "execute_dag", boom)
    dag_id = _seed(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "failed", "error": "cyclic DAG rejected before execution"}


def test_run_dag_projection_failure_does_not_rewrite_execution(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.dag_run_store as history
    import services.graph_runner as graph_runner

    async def ok(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        return _completed_result("run-with-history-failure")

    def unavailable() -> Any:
        raise RuntimeError("history unavailable")

    monkeypatch.setattr(graph_runner, "execute_dag", ok)
    monkeypatch.setattr(history, "get_dag_run_store", unavailable)

    dag_id = _seed(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["run_id"] == "run-with-history-failure"


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
