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

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

pytestmark = pytest.mark.usefixtures("canonical_run_spine")

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
def test_http_runs_in_two_workspaces_are_distinct_canonical_runs_with_projections(
    admin_client: TestClient, stored_dag: str
) -> None:
    from services.dag_run_store import get_dag_run_store

    workspace_a = _create_workspace(admin_client, "HTTP parity A")
    workspace_b = _create_workspace(admin_client, "HTTP parity B")

    body_a = admin_client.post(f"/v1/dags/{stored_dag}/run", json={"workspace_id": workspace_a})
    body_b = admin_client.post(f"/v1/dags/{stored_dag}/run", json={"workspace_id": workspace_b})

    run_a, run_b = body_a.json()["run_id"], body_b.json()["run_id"]
    assert run_a and run_b and run_a != run_b
    record_a, record_b = _canonical_record(run_a), _canonical_record(run_b)
    assert (record_a.run.workspace_id, record_b.run.workspace_id) == (workspace_a, workspace_b)
    assert record_a.run.project_id != record_b.run.project_id
    for run_id, workspace_id in ((run_a, workspace_a), (run_b, workspace_b)):
        projection = get_dag_run_store().get_run(run_id)
        assert projection is not None
        assert projection["workspace_id"] == workspace_id


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_ws_run_is_interactive_and_audited_like_http(
    admin_client: TestClient, stored_dag: str
) -> None:
    import stores

    workspace_id = _create_workspace(admin_client, "Parity mode")
    audited_before = {
        key
        for key, entry in stores.audit_log.items()
        if entry["action"] == "dag_run" and entry["target"] == stored_dag
    }

    ws_run = _run_over_socket(admin_client, stored_dag, workspace_id)[-1]["run_id"]
    http_run = admin_client.post(
        f"/v1/dags/{stored_dag}/run", json={"workspace_id": workspace_id}
    ).json()["run_id"]

    for run_id in (ws_run, http_run):
        assert _canonical_record(run_id).run.provenance["execution_mode"] == "interactive"
    audited = [
        entry
        for key, entry in stores.audit_log.items()
        if entry["action"] == "dag_run"
        and entry["target"] == stored_dag
        and key not in audited_before
    ]
    assert [entry["actor"] for entry in audited] == ["admin", "admin"]


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
@pytest.mark.asyncio
async def test_stream_hands_over_the_canonical_result_before_any_node_frame(
    stored_dag: str,
) -> None:
    """A socket whose client left fails on the first NodeRun frame it sends;
    the result must already be with ``on_result`` by then."""
    import stores
    from services.dag_execution_scope import authorize_hive_dag_scope
    from services.graph_runner import execute_dag_streaming
    from services.workspace_authority import canonical_store_for_tests

    await canonical_store_for_tests().create(
        creator_user_id="admin", workspace_id="parity-abandoned", name="Abandoned"
    )
    scope = await authorize_hive_dag_scope(workspace_id="parity-abandoned", user_id="admin")
    handed_over: list[dict[str, Any]] = []

    async def on_result(result: dict[str, Any]) -> None:
        handed_over.append(result)

    stream = execute_dag_streaming(stores.dags[stored_dag], scope=scope, on_result=on_result)
    assert (await anext(stream))["status"] == "started"
    first_node_frame = await anext(stream)
    await stream.aclose()

    assert first_node_frame["status"] == "node_complete"
    assert [result["run_id"] for result in handed_over] == [first_node_frame["run_id"]]


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
    from services.dag_agents import _container

    from maistro.runs.model import RunStatus

    async def read_ids():
        runs = _container().run_store
        return {run.run_id for status in RunStatus for run in await runs.list_by_status(status)}

    return asyncio.run(read_ids())


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
    unknown = admin_client.post(
        f"/v1/dags/{stored_dag}/run", json={"workspace_id": "parity-no-such-workspace"}
    )
    assert unknown.status_code == 403
    assert _run_ids() == before


@pytest.fixture
def sqlite_member_root_project(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Wire a SQLite canonical WorkspaceStore; yield the member Workspace's Root Project."""
    # maistro-core's optional `sqlite` extra: absent from Hive's requirements.txt
    # job, installed by the `uv sync --all-extras` coverage job that runs this suite.
    aiosqlite = pytest.importorskip("aiosqlite")
    import services.workspace_authority as workspace_authority

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    async def _open() -> tuple[Any, Any, str]:
        conn = await aiosqlite.connect(":memory:")
        project_store = SqliteProjectScopeStore(conn)
        await project_store.ensure_schema()
        store = SqliteWorkspaceStore(conn, project_store=project_store)
        await store.ensure_schema()
        await store.create(creator_user_id="admin", workspace_id="sqlite-member", name="Mine")
        await store.create(
            creator_user_id="someone-else", workspace_id="sqlite-foreign", name="Theirs"
        )
        root = await project_store.root_for_workspace("sqlite-member")
        return conn, store, root.project_id

    loop = asyncio.new_event_loop()
    conn, store, root_project_id = loop.run_until_complete(_open())
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: store)
    from types import SimpleNamespace

    from services.engine import get_engine

    from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
    from maistro.runs.store import InMemoryRunStore

    runs = InMemoryRunStore(project_store=store.project_store)
    monkeypatch.setattr(
        get_engine(),
        "_agent_port",
        SimpleNamespace(
            container=SimpleNamespace(
                run_store=runs,
                graph_run_store=CanonicalDurableRunStore(runs, InMemoryGraphContinuationStore()),
            )
        ),
    )
    yield root_project_id
    loop.run_until_complete(conn.close())
    loop.close()


@pytest.fixture
def canonical_run_spine(_chat_spine_container: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Wire a real canonical Container onto the engine.

    The fixture exposes Workspace and Project scope authority alongside the
    canonical Run and continuation owners. Model dispatch remains faked at
    the terminal boundary; no production standalone lifecycle is needed.
    """
    from types import SimpleNamespace

    from services.engine import get_engine

    container = _chat_spine_container
    spine = SimpleNamespace(
        run_store=container.run_store,
        graph_run_store=container.graph_run_store,
        workspace_store=container.workspace_store,
        project_scope_store=container.project_scope_store,
    )
    monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=spine))
    yield container


async def _canonical_run_ids_for_dag(container: Any, *, workspace_id: str, dag_id: str) -> set[str]:
    """Canonical Runs admitted for ``dag_id`` in ``workspace_id``, any status.

    Reads the bare canonical ``RunStore`` (``container.run_store``) -- what
    ``RunStore.create_run()`` actually admits into -- rather than
    ``graph_run_store``, the ``DurableRunStore`` wrapper that only assembles a
    record once a Graph continuation exists. A Run admitted and then abandoned
    before it ever reaches ``run_durable_graph`` (e.g. a double-admission bug
    that leaves the extra Run ``queued`` with no continuation) has no
    continuation and is invisible to ``graph_run_store``, but must still count
    against "exactly one". Every status is swept, not just ``completed``, for
    the same reason.
    """
    from maistro.runs.model import RunStatus

    ids: set[str] = set()
    for status in RunStatus:
        runs = await container.run_store.list_by_status(
            status, workspace_id=workspace_id, admission_source="hive_legacy_dag", limit=100
        )
        ids.update(run.run_id for run in runs if run.provenance.get("legacy_dag_id") == dag_id)
    return ids


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_http_and_ws_run_each_admit_exactly_one_canonical_run(
    admin_client: TestClient, stored_dag: str, canonical_run_spine: Any
) -> None:
    from services.dag_run_store import get_dag_run_store

    workspace_id = _create_workspace(admin_client, "Exactly one canonical run")

    def _canonical_run_ids() -> set[str]:
        return asyncio.run(
            _canonical_run_ids_for_dag(
                canonical_run_spine, workspace_id=workspace_id, dag_id=stored_dag
            )
        )

    before_http = _canonical_run_ids()
    http_response = admin_client.post(
        f"/v1/dags/{stored_dag}/run", json={"workspace_id": workspace_id}
    )
    assert http_response.status_code == 200, http_response.text
    http_run_id = http_response.json()["run_id"]
    after_http = _canonical_run_ids()

    assert after_http - before_http == {http_run_id}
    http_projection = get_dag_run_store().get_run(http_run_id)
    assert http_projection is not None
    assert http_projection["canonical_run_id"] == http_run_id

    before_ws = _canonical_run_ids()
    ws_run_id = _run_over_socket(admin_client, stored_dag, workspace_id)[-1]["run_id"]
    after_ws = _canonical_run_ids()

    assert after_ws - before_ws == {ws_run_id}
    ws_projection = get_dag_run_store().get_run(ws_run_id)
    assert ws_projection is not None
    assert ws_projection["canonical_run_id"] == ws_run_id


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_sqlite_canonical_store_authorizes_member_and_refuses_non_member_on_both_transports(
    admin_client: TestClient,
    stored_dag: str,
    sqlite_member_root_project: str,
) -> None:
    import stores
    from services.dag_run_store import get_dag_run_store

    assert "sqlite-member" not in stores.workspaces
    assert "sqlite-foreign" not in stores.workspaces

    member = admin_client.post(f"/v1/dags/{stored_dag}/run", json={"workspace_id": "sqlite-member"})
    assert member.status_code == 200, member.text
    assert member.json()["status"] == "completed"
    assert member.json()["result"]["project_id"] == sqlite_member_root_project

    before = _run_ids()
    outsider = admin_client.post(
        f"/v1/dags/{stored_dag}/run", json={"workspace_id": "sqlite-foreign"}
    )
    assert outsider.status_code == 403
    assert _run_ids() == before

    terminal = _run_over_socket(admin_client, stored_dag, "sqlite-member")[-1]
    assert terminal["status"] == "completed"
    assert _canonical_record(terminal["run_id"]).run.project_id == sqlite_member_root_project
    projection = get_dag_run_store().get_run(terminal["run_id"])
    assert projection is not None
    assert projection["workspace_id"] == "sqlite-member"
    assert projection["project_id"] == sqlite_member_root_project

    before = _run_ids()
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        admin_client.websocket_connect(f"/v1/ws/dags/{stored_dag}/run?workspace_id=sqlite-foreign"),
    ):
        pass
    assert refused.value.code == POLICY_VIOLATION
    assert _run_ids() == before


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_ws_live_stream_records_projection_incrementally_with_sequence_identity(
    admin_client: TestClient, stored_dag: str
) -> None:
    """#1183: the websocket Run streams progress while executing, and the
    projection is written incrementally — every node frame is durable before
    it is sent, carries the projection's sequence number, and the run record
    holds the contiguous event history a reconnecting consumer replays."""
    from services.dag_run_store import get_dag_run_store

    workspace_id = _create_workspace(admin_client, "Parity live")
    frames = _run_over_socket(admin_client, stored_dag, workspace_id)

    assert frames[0]["status"] == "started"
    assert frames[0]["heartbeat_seconds"] > 0
    terminal = frames[-1]
    assert terminal["status"] == "completed"
    run_id = terminal["run_id"]

    node_frames = [frame for frame in frames if frame["status"] == "node_complete"]
    assert node_frames, "live mode must deliver node frames"
    for frame in node_frames:
        assert frame["run_id"] == run_id
        assert isinstance(frame["seq"], int) and frame["seq"] >= 1

    projection = get_dag_run_store().get_run(run_id)
    assert projection is not None
    assert projection["status"] == "completed"
    seqs = [event["seq"] for event in projection["events"]]
    # Contiguous 1..N: started + completed per node, in execution order.
    assert seqs == list(range(1, len(seqs) + 1))
    assert len(seqs) >= 2 * len(node_frames)
    types = [event["event_type"] for event in projection["events"]]
    assert types[0] == "pm_node_started"
    assert types.count("pm_node_completed") == len(node_frames)


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
@pytest.mark.asyncio
async def test_live_projection_is_scoped_from_its_first_event(
    admin_client: TestClient, stored_dag: str
) -> None:
    """#1183: a live-run projection row is born with its canonical Workspace.

    The websocket route records node events before the Run settles — the row
    must be inspectable (and its SSE stream authorizable) from the first live
    event, at the same Workspace boundary the execution was admitted into,
    not only after `record_result` lands the terminal scope.
    """
    from services.dag_execution_scope import authorize_hive_dag_scope
    from services.dag_run_inspection import can_inspect_run
    from services.dag_run_live import LiveRunProjection

    workspace_id = _create_workspace(admin_client, "Live scope")
    scope = await authorize_hive_dag_scope(workspace_id=workspace_id, user_id="admin")

    from services.dag_run_store import get_dag_run_store

    assert not await can_inspect_run("admin", "run-live-scope")

    recorder = LiveRunProjection(dag_id=stored_dag, scope=scope)
    seq = await recorder.record_event(
        {
            "kind": "node_started",
            "run_id": "run-live-scope",
            "node_run_id": "nr-1",
            "attempt_id": "a-1",
            "node_id": "n1",
            "role": "worker",
        }
    )
    assert seq == 1

    # Mid-run: the row exists, is scoped, and is inspectable — the gate the
    # SSE stream authorizes against answers before any terminal result.
    assert await can_inspect_run("admin", "run-live-scope")
    detail = get_dag_run_store().get_run("run-live-scope")
    assert detail is not None
    assert detail["workspace_id"] == workspace_id
    assert detail["dag_id"] == stored_dag
    assert detail["canonical_run_id"] == "run-live-scope"

    await recorder.record_result({"run_id": "run-live-scope", "status": "completed"})
    detail = get_dag_run_store().get_run("run-live-scope")
    assert detail is not None
    assert detail["status"] == "completed"


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
@pytest.mark.asyncio
async def test_live_projection_swallows_malformed_events_and_store_failures(
    admin_client: TestClient,
    stored_dag: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#1183: projection recording is presentation and may not break the Run.

    A malformed node event records nothing (and mints no sequence cursor), a
    failing projection store is logged and swallowed for both the live-event
    and the terminal-result path, and a result without a run identity is
    dropped on the floor — the executing Run's outcome must never flip
    because the projection row could not be written.
    """
    import logging

    import services.dag_run_store as dag_run_store
    from services.dag_execution_scope import authorize_hive_dag_scope
    from services.dag_run_live import LiveRunProjection

    workspace_id = _create_workspace(admin_client, "Live resilience")
    scope = await authorize_hive_dag_scope(workspace_id=workspace_id, user_id="admin")
    recorder = LiveRunProjection(dag_id=stored_dag, scope=scope)

    # Not events: no run identity, no node identity, no known kind. Each is
    # refused before the store is touched, so no projection row or cursor is
    # minted from a frame the consumer could never resume from.
    assert await recorder.record_event({"kind": "node_started"}) is None
    assert await recorder.record_event({"kind": "node_started", "run_id": "r"}) is None
    assert (
        await recorder.record_event({"kind": "node_started", "run_id": "r", "node_id": ""}) is None
    )
    assert (
        await recorder.record_event({"kind": "node_exploded", "run_id": "r", "node_id": "n1"})
        is None
    )

    def _explode() -> Any:
        raise RuntimeError("projection store down")

    monkeypatch.setattr(dag_run_store, "get_dag_run_store", _explode)
    with caplog.at_level(logging.WARNING, logger="hive.dag_run_live"):
        # Live event: the failure is logged, never raised ...
        assert (
            await recorder.record_event({"kind": "node_started", "run_id": "r", "node_id": "n1"})
            is None
        )
        assert "dag_run_live_projection_event_not_recorded" in caplog.text
        # ... and the terminal result fails just as softly.
        await recorder.record_result({"run_id": "r", "status": "completed"})
        assert "dag_run_live_projection_result_not_recorded" in caplog.text

    # A result without a run identity records nothing at all — with the store
    # back, the absence of a row proves the guard short-circuits first.
    monkeypatch.undo()
    await recorder.record_result({"status": "completed"})
    assert dag_run_store.get_dag_run_store().get_run("r") is None
