"""WS/HTTP parity for the shipped DAG Run controls (#766).

Only the model boundary is replaced (``graph_runner._build_llm_call``). Workspace
membership is created through the canonical authority, execution runs through
``canonical_dag_runner``, and the Recent Runs projection is read back from the
process ``DagRunStore``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import aiosqlite
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

POLICY_VIOLATION = 1008
_SECRET = "postgres://svc:hunter2@db.internal/prod"


def _fake_llm_builder(*, fail_prompt: str | None = None):
    def build(_on_response: Any = None):
        async def call(messages: list[dict[str, Any]], **_kwargs: Any) -> str:
            system = str(messages[0]["content"])
            if fail_prompt and fail_prompt in system:
                raise RuntimeError("intentional node failure")
            return f"ok:{system}"

        return call

    return build


def _stored_dag(dag_id: str, *, prompt: str = "hello") -> dict[str, Any]:
    return {
        "id": dag_id,
        "name": dag_id,
        "description": "",
        "nodes": [
            {
                "id": "n1",
                "role": "worker",
                "name": "n1",
                "prompt": prompt,
                "config": {"execution_tier": "safe"},
            }
        ],
        "edges": [],
    }


@pytest.fixture
def stored_dag(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    import services.graph_runner as graph_runner
    import stores

    monkeypatch.setattr(graph_runner, "_build_llm_call", _fake_llm_builder(fail_prompt="fail-me"))
    dag_id = "parity-dag"
    stores.dags[dag_id] = _stored_dag(dag_id)
    yield dag_id
    stores.dags.pop(dag_id, None)


def _create_workspace(client: TestClient, name: str) -> str:
    response = client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert response.status_code in (200, 201), response.text
    return str(response.json()["id"])


def _run_over_socket(client: TestClient, dag_id: str, workspace_id: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    with client.websocket_connect(f"/v1/ws/dags/{dag_id}/run?workspace_id={workspace_id}") as ws:
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame.get("status") in ("completed", "failed", "cancelled"):
                return frames


def _canonical_record(run_id: str) -> Any:
    from services.dag_agents import get_run_store

    return asyncio.run(get_run_store().get(run_id))


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_ws_runs_in_two_workspaces_are_distinct_canonical_runs_with_projections(
    admin_client: TestClient, stored_dag: str
) -> None:
    from services.dag_run_store import get_dag_run_store

    workspace_a = _create_workspace(admin_client, "Parity A")
    workspace_b = _create_workspace(admin_client, "Parity B")

    terminal_a = _run_over_socket(admin_client, stored_dag, workspace_a)[-1]
    terminal_b = _run_over_socket(admin_client, stored_dag, workspace_b)[-1]

    assert terminal_a["status"] == terminal_b["status"] == "completed"
    run_a, run_b = terminal_a["run_id"], terminal_b["run_id"]
    assert run_a and run_b and run_a != run_b

    record_a, record_b = _canonical_record(run_a), _canonical_record(run_b)
    assert record_a.run.workspace_id == workspace_a
    assert record_b.run.workspace_id == workspace_b
    assert record_a.run.project_id and record_b.run.project_id
    assert record_a.run.project_id != record_b.run.project_id

    for run_id, workspace_id, record in (
        (run_a, workspace_a, record_a),
        (run_b, workspace_b, record_b),
    ):
        projection = get_dag_run_store().get_run(run_id)
        assert projection is not None
        assert projection["canonical_run_id"] == run_id
        assert projection["workspace_id"] == workspace_id
        assert projection["project_id"] == record.run.project_id
        assert projection["dag_id"] == stored_dag
        assert projection["status"] == "completed"


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_ws_failed_node_projects_the_canonical_run_like_http(
    admin_client: TestClient, stored_dag: str
) -> None:
    import stores
    from services.dag_run_store import get_dag_run_store

    stores.dags[stored_dag] = _stored_dag(stored_dag, prompt="fail-me")
    workspace_id = _create_workspace(admin_client, "Parity failing")

    terminal = _run_over_socket(admin_client, stored_dag, workspace_id)[-1]
    http = admin_client.post(f"/v1/dags/{stored_dag}/run", json={"workspace_id": workspace_id})

    assert terminal["status"] == "failed"
    assert terminal["run_id"]
    assert _canonical_record(terminal["run_id"]).run.status.value == "failed"
    assert {k: terminal[k] for k in ("status", "error")} == {
        k: http.json()[k] for k in ("status", "error")
    }
    assert terminal["run_id"] != http.json()["run_id"]
    for run_id in (terminal["run_id"], http.json()["run_id"]):
        projection = get_dag_run_store().get_run(run_id)
        assert projection is not None
        assert projection["status"] == "failed"
        assert projection["canonical_run_id"] == run_id
        assert projection["workspace_id"] == workspace_id


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_ws_malformed_dag_failure_frame_names_only_the_exception_kind(
    admin_client: TestClient, stored_dag: str
) -> None:
    import stores

    stores.dags[stored_dag] = {"id": stored_dag, "nodes": [_SECRET], "edges": []}
    workspace_id = _create_workspace(admin_client, "Parity malformed")

    with admin_client.websocket_connect(
        f"/v1/ws/dags/{stored_dag}/run?workspace_id={workspace_id}"
    ) as ws:
        frame = ws.receive_json()

    assert frame == {
        "status": "failed",
        "error": "AttributeError: execution failed; see server logs",
    }


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_ws_unexpected_failure_frame_names_only_the_exception_kind(
    admin_client: TestClient, stored_dag: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.canonical_dag_runner as canonical_dag_runner

    async def explode(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ConnectionError(_SECRET)

    # The one non-model replacement: an infrastructure failure below the
    # canonical runner, which the transport must not echo to the client.
    monkeypatch.setattr(canonical_dag_runner, "run_durable_graph", explode)
    workspace_id = _create_workspace(admin_client, "Parity infra failure")

    terminal = _run_over_socket(admin_client, stored_dag, workspace_id)[-1]

    assert terminal == {
        "status": "failed",
        "error": "ConnectionError: execution failed; see server logs",
    }


def _run_ids() -> set[str]:
    from services.dag_agents import get_run_store

    store = get_run_store()
    return set(store._rows)


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_http_run_in_foreign_workspace_is_refused_before_execution(
    admin_client: TestClient, stored_dag: str
) -> None:
    from services.workspace_authority import canonical_store_for_tests

    asyncio.run(
        canonical_store_for_tests().create(
            creator_user_id="someone-else", workspace_id="parity-foreign", name="Foreign"
        )
    )
    before = _run_ids()

    response = admin_client.post(
        f"/v1/dags/{stored_dag}/run", json={"workspace_id": "parity-foreign"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "DAG Workspace scope is not authorized"
    assert _run_ids() == before


@pytest.fixture
def sqlite_workspace_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[SqliteWorkspaceStore]:
    import services.workspace_authority as workspace_authority

    async def _open() -> tuple[aiosqlite.Connection, SqliteWorkspaceStore]:
        conn = await aiosqlite.connect(":memory:")
        project_store = SqliteProjectScopeStore(conn)
        await project_store.ensure_schema()
        store = SqliteWorkspaceStore(conn, project_store=project_store)
        await store.ensure_schema()
        await store.create(creator_user_id="admin", workspace_id="sqlite-member", name="Mine")
        await store.create(
            creator_user_id="someone-else", workspace_id="sqlite-foreign", name="Theirs"
        )
        return conn, store

    loop = asyncio.new_event_loop()
    conn, store = loop.run_until_complete(_open())
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: store)
    yield store
    loop.run_until_complete(conn.close())
    loop.close()


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_sqlite_canonical_store_authorizes_member_and_refuses_non_member_on_both_transports(
    admin_client: TestClient,
    stored_dag: str,
    sqlite_workspace_store: SqliteWorkspaceStore,
) -> None:
    import stores

    assert "sqlite-member" not in stores.workspaces
    assert "sqlite-foreign" not in stores.workspaces

    member = admin_client.post(f"/v1/dags/{stored_dag}/run", json={"workspace_id": "sqlite-member"})
    assert member.status_code == 200, member.text
    assert member.json()["status"] == "completed"

    before = _run_ids()
    outsider = admin_client.post(
        f"/v1/dags/{stored_dag}/run", json={"workspace_id": "sqlite-foreign"}
    )
    assert outsider.status_code == 403

    terminal = _run_over_socket(admin_client, stored_dag, "sqlite-member")[-1]
    assert terminal["status"] == "completed"
    assert terminal["run_id"]

    before = _run_ids()
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        admin_client.websocket_connect(f"/v1/ws/dags/{stored_dag}/run?workspace_id=sqlite-foreign"),
    ):
        pass
    assert refused.value.code == POLICY_VIOLATION
    assert _run_ids() == before
