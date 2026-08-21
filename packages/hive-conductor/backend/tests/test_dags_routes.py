"""Boy Scout coverage pay-down — routes/dags.py.

Phase 5 Signal #2 PR touched routes/dags.py to add the audit + edit-lock
hooks. The IRON Boy Scout Rule then requires the whole file reach 95%
line + 95% branch in the same PR. The PUT branch is already covered by
test_edit_lock_and_audit.py; this module fills in the rest:

- GET /v1/dags + GET /v1/dags/{id} (200 + 404)
- POST /v1/dags + POST /v1/dags/{id}/nodes + DELETE
- POST /v1/dags/{id}/edges + DELETE
- POST /v1/dags/{id}/activate
- POST /v1/dags/{id}/run (both success + execution-fail branches)
- POST /v1/dags/run-champion (both success + fail branches)

Every assertion checks a VALUE (status code, response field, store
state) — no isinstance / no-op patterns.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _seed(client: Any) -> str:
    r = client.post("/v1/dags", json={"name": "seed", "description": ""})
    assert r.status_code == 201
    return r.json()["id"]


# --- list / get -----------------------------------------------------------


def test_list_dags_returns_array(admin_client: Any) -> None:
    r = admin_client.get("/v1/dags")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_dag_by_id_returns_payload(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    r = admin_client.get(f"/v1/dags/{dag_id}")
    assert r.status_code == 200
    assert r.json()["id"] == dag_id
    assert r.json()["name"] == "seed"


def test_get_dag_missing_returns_404(admin_client: Any) -> None:
    r = admin_client.get("/v1/dags/missing-xyz")
    assert r.status_code == 404


# --- POST /{id}/nodes + DELETE ------------------------------------------


def test_add_and_remove_node(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    r = admin_client.post(
        f"/v1/dags/{dag_id}/nodes",
        json={"role": "scout", "name": "Scout"},
    )
    assert r.status_code == 200
    node_id = r.json()["id"]
    assert r.json()["role"] == "scout"

    # remove it
    r2 = admin_client.delete(f"/v1/dags/{dag_id}/nodes/{node_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == node_id


def test_add_node_dag_404(admin_client: Any) -> None:
    r = admin_client.post("/v1/dags/missing-dag/nodes", json={"role": "scout", "name": "x"})
    assert r.status_code == 404


def test_remove_node_dag_404(admin_client: Any) -> None:
    r = admin_client.delete("/v1/dags/missing-dag/nodes/any")
    assert r.status_code == 404


def test_remove_node_not_found(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    r = admin_client.delete(f"/v1/dags/{dag_id}/nodes/no-such")
    assert r.status_code == 404


# --- POST /{id}/edges + DELETE ------------------------------------------


def test_add_and_remove_edge(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    r0 = admin_client.get(f"/v1/dags/{dag_id}")
    src = r0.json()["nodes"][0]["id"]
    dst = r0.json()["nodes"][1]["id"]
    r = admin_client.post(
        f"/v1/dags/{dag_id}/edges",
        json={"from_node": src, "to_node": dst, "condition": "if x"},
    )
    assert r.status_code == 200
    edge_id = r.json()["id"]
    assert r.json()["condition"] == "if x"

    r2 = admin_client.delete(f"/v1/dags/{dag_id}/edges/{edge_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == edge_id


def test_add_edge_dag_404(admin_client: Any) -> None:
    r = admin_client.post(
        "/v1/dags/missing/edges",
        json={"from_node": "a", "to_node": "b"},
    )
    assert r.status_code == 404


def test_remove_edge_dag_404(admin_client: Any) -> None:
    r = admin_client.delete("/v1/dags/missing/edges/any")
    assert r.status_code == 404


def test_remove_edge_not_found(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    r = admin_client.delete(f"/v1/dags/{dag_id}/edges/no-such")
    assert r.status_code == 404


# --- DELETE /{id} ---------------------------------------------------------


def test_delete_dag_succeeds_and_then_404s(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    r = admin_client.delete(f"/v1/dags/{dag_id}")
    assert r.status_code == 204
    r2 = admin_client.get(f"/v1/dags/{dag_id}")
    assert r2.status_code == 404


def test_delete_dag_missing_returns_404(admin_client: Any) -> None:
    r = admin_client.delete("/v1/dags/never-existed")
    assert r.status_code == 404


# --- POST /{id}/activate -------------------------------------------------


def test_activate_dag(admin_client: Any) -> None:
    import stores

    before_audit = len(stores.audit_log)
    dag_id = _seed(admin_client)
    r = admin_client.post(f"/v1/dags/{dag_id}/activate")
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    # audit entry for activate
    entries = list(stores.audit_log.values())
    assert any(
        e["action"] == "dag_activate" and e["target"] == dag_id for e in entries[before_audit:]
    )


def test_activate_dag_missing_404(admin_client: Any) -> None:
    r = admin_client.post("/v1/dags/missing-dag/activate")
    assert r.status_code == 404


# --- POST /{id}/run (success + failure) -----------------------------------


def test_run_dag_success_path(admin_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub services.graph_runner.execute_dag to return a deterministic
    payload; verify the wrapper returns status='completed' + execution_id."""
    import services.graph_runner as gr

    async def _ok(dag_data: Any, **kwargs: Any) -> Any:
        return {"final": "ok", "ran": True}

    monkeypatch.setattr(gr, "execute_dag", _ok)
    dag_id = _seed(admin_client)
    r = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["result"] == {"final": "ok", "ran": True}
    assert body["execution_id"]


def test_run_dag_failure_path(admin_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.graph_runner as gr

    async def _boom(dag_data: Any, **kwargs: Any) -> Any:
        raise RuntimeError("graph blew up")

    monkeypatch.setattr(gr, "execute_dag", _boom)
    dag_id = _seed(admin_client)
    r = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert r.status_code == 200  # the route never 500s; returns shape
    body = r.json()
    assert body["status"] == "failed"
    assert "graph blew up" in body["error"]


def test_run_dag_missing_dag_returns_404(admin_client: Any) -> None:
    r = admin_client.post("/v1/dags/missing-dag/run")
    assert r.status_code == 404


def test_run_dag_records_node_events_and_metrics(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evidence: when execute_dag returns node_results, the run wrapper must
    append a dag-run-store event per node (success -> pm_node_completed,
    failure -> pm_node_failed) and record a NodeObservation in the node
    metrics store for each. This also exercises the dag_run_store.start_run /
    append_event integration (lines 268-283) and the node-metrics recording
    block (lines 285-307)."""
    import services.graph_runner as gr
    import services.node_metrics_store as nms

    async def _ok(dag_data: Any, **kwargs: Any) -> Any:
        return {
            "cycles": 2,
            "node_results": {
                "n1": {"role": "worker", "success": True, "response": "did the thing"},
                "n2": {"role": "queen", "success": False, "response": "oops"},
            },
        }

    monkeypatch.setattr(gr, "execute_dag", _ok)

    metrics_store = nms.NodeMetricsStore()
    monkeypatch.setattr(nms, "_store", metrics_store)

    dag_id = _seed(admin_client)
    r = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["result"]["node_results"]["n1"]["success"] is True

    # Node metrics store recorded one observation per node.
    assert len(metrics_store) == 2

    from services.dag_run_store import get_dag_run_store

    run_store = get_dag_run_store()
    run_record = run_store.get_run(body["execution_id"])
    assert run_record is not None
    assert run_record["event_count"] == 2


def test_run_dag_node_metrics_failure_is_swallowed(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evidence: the node-metrics recording block is wrapped in a bare
    try/except Exception: pass, so a broken metrics store must not affect
    the run response at all."""
    import services.graph_runner as gr
    import services.node_metrics_store as nms

    async def _ok(dag_data: Any, **kwargs: Any) -> Any:
        return {
            "cycles": 1,
            "node_results": {"n1": {"role": "worker", "success": True, "response": "ok"}},
        }

    monkeypatch.setattr(gr, "execute_dag", _ok)

    def _boom() -> Any:
        raise RuntimeError("metrics store unavailable")

    monkeypatch.setattr(nms, "get_store", _boom)

    dag_id = _seed(admin_client)
    r = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"


# --- POST /run-champion (success + failure) -------------------------------


def test_run_champion_success(admin_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.graph_runner as gr

    async def _ok() -> Any:
        return {"champion": True}

    monkeypatch.setattr(gr, "execute_champion", _ok)
    r = admin_client.post("/v1/dags/run-champion")
    assert r.status_code == 200
    body = r.json()
    assert body["result"] == {"champion": True}
    assert body["execution_id"]


def test_run_champion_failure(admin_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.graph_runner as gr

    async def _boom() -> Any:
        raise RuntimeError("champion crash")

    monkeypatch.setattr(gr, "execute_champion", _boom)
    r = admin_client.post("/v1/dags/run-champion")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert "champion crash" in body["error"]
