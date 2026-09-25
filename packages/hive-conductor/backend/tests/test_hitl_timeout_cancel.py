"""Conductor delegates HITL timeout and cancellation to the durable store."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import pytest
from services.workspace_authority import create_workspace

from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.lifecycle import transition_node_run, transition_run
from maistro.runs.model import GraphSnapshot, NodeRun, Run, RunStatus

pytestmark = [pytest.mark.contract("behavioral")]


class _SeedPaused(Protocol):
    async def __call__(self, run_id: str, *, deadline: datetime) -> None: ...


_Seeded = tuple[Any, InMemoryDurableRunStore, _SeedPaused]


def _paused_node_run(run_id: str) -> NodeRun:
    node_run = NodeRun(run_id=run_id, node_id="ask", ordinal=1)
    node_run = transition_node_run(node_run, RunStatus.QUEUED)
    node_run = transition_node_run(node_run, RunStatus.RUNNING)
    return transition_node_run(node_run, RunStatus.PAUSED)


def _paused_record(
    run_id: str,
    *,
    deadline: datetime,
    workspace_id: str = "ws-hitl-settlement",
    project_id: str = "project-hitl-settlement",
) -> Any:
    from maistro.graph.durable_runs.types import DurableRunRecord

    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="approval",
        nodes=[Node(node_id="ask", node_type="human.ask_question")],
    )
    run = Run(
        run_id=run_id,
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
    )
    run = transition_run(run, RunStatus.QUEUED)
    run = transition_run(run, RunStatus.RUNNING)
    run = transition_run(run, RunStatus.PAUSED)
    pause = {
        "kind": "hitl",
        "metadata": {"question": "Ship it?", "timeout_seconds": 60},
        "resume_at": deadline.isoformat(),
    }
    state = GraphExecutionState(
        run_id=run_id,
        active_node_ids=("ask",),
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {"ask": pause},
            "pause": pause,
        },
    )
    return DurableRunRecord(
        run=run,
        graph_state=state,
        node_runs=(_paused_node_run(run_id),),
        resume_at=deadline,
        version=1,
    )


@pytest.fixture
def reviewer_client():
    import stores
    from fastapi.testclient import TestClient
    from main import app

    stores.users["hitl-expiry-reviewer"] = stores.users["user"].model_copy(
        update={
            "id": "hitl-expiry-reviewer",
            "username": "hitl-expiry-reviewer",
            "permissions": ["dags.write"],
        }
    )
    client = TestClient(app)
    try:
        login = client.post(
            "/v1/auth/login",
            json={"username": "hitl-expiry-reviewer", "password": "testpass"},
        )
        assert login.status_code == 200
        elevated = client.post(
            "/v1/auth/elevate",
            json={
                "password": "testpass",
                "permissions": ["dags.write"],
                "task_id": "hitl-expiry-reviewer-test",
            },
        )
        assert elevated.status_code == 200
        yield client
    finally:
        stores.users.pop("hitl-expiry-reviewer", None)


@pytest.fixture
def seeded(admin_client: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Seeded]:
    from services import dag_agents

    # This fixture seeds the legacy document-shaped store directly. Bind it to
    # the route only as an explicit test seam; production `_store()` refuses
    # this store and requires the Container's canonical projection.
    store = dag_agents.get_run_store()
    assert isinstance(store, InMemoryDurableRunStore)
    monkeypatch.setattr(dag_agents, "get_canonical_run_store", lambda: store)
    created: list[str] = []

    async def _seed(run_id: str, *, deadline: datetime) -> None:
        workspace = await create_workspace(
            creator_user_id="admin",
            name=f"HITL timeout workspace-{run_id}",
            persona_template_id="default",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )
        from services.workspace_authority import canonical_store_for_tests

        root = await canonical_store_for_tests().project_store.root_for_workspace(workspace.id)
        await store.create(
            _paused_record(
                run_id,
                deadline=deadline,
                workspace_id=workspace.id,
                project_id=root.project_id,
            )
        )
        created.append(run_id)

    yield admin_client, store, _seed
    for run_id in created:
        store._rows.pop(run_id, None)


@pytest.mark.ac("SPEC-083026-73c1/AC-6")
def test_hitl_endpoint_fails_closed_without_canonical_spine(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded Conductor must not present ephemeral human work as durable."""
    from services import dag_agents

    def _unavailable() -> Any:
        raise RuntimeError("canonical graph execution spine is unavailable")

    monkeypatch.setattr(dag_agents, "get_canonical_run_store", _unavailable)

    response = admin_client.get("/v1/hitl/pending")

    assert response.status_code == 503
    assert "canonical execution spine" in response.json()["detail"]


async def test_cancel_endpoint_requests_canonical_settlement(seeded: _Seeded) -> None:
    client, store, seed = seeded
    await seed("hitl-api-cancel", deadline=datetime.now(UTC) + timedelta(hours=1))

    response = client.post("/v1/hitl/hitl-api-cancel/ask/cancel")

    assert response.status_code == 200
    assert response.json()["run_status"] == RunStatus.CANCELLED.value
    persisted = await store.get("hitl-api-cancel")
    assert persisted is not None
    assert persisted.run.status is RunStatus.CANCELLED
    assert persisted.node_runs[0].status is RunStatus.CANCELLED
    assert persisted.hitl_answers == {}
    assert persisted.graph_state.metadata["hitl_settlements"]["ask"]["outcome"] == "cancelled"


async def test_cancel_endpoint_maps_store_refusals(seeded: _Seeded) -> None:
    client, _store, seed = seeded
    assert client.post("/v1/hitl/no-such-run/ask/cancel").status_code == 404
    await seed("hitl-api-cancel-twice", deadline=datetime.now(UTC) + timedelta(hours=1))
    assert client.post("/v1/hitl/hitl-api-cancel-twice/ask/cancel").status_code == 200

    refused = client.post("/v1/hitl/hitl-api-cancel-twice/ask/cancel")

    assert refused.status_code == 409
    assert "not paused" in refused.json()["detail"]


@pytest.mark.ac("SPEC-083026-73c1/AC-6")
async def test_expiry_endpoint_runs_a_bounded_store_tick(seeded: _Seeded) -> None:
    client, store, seed = seeded
    elapsed = datetime.now(UTC) - timedelta(minutes=1)
    await seed("hitl-api-expire-first", deadline=elapsed)
    await seed("hitl-api-expire-second", deadline=elapsed)

    response = client.post("/v1/hitl/expire?limit=1")

    assert response.status_code == 200
    assert response.json()["expired"] == 1
    settled = [
        await store.get(run_id) for run_id in ("hitl-api-expire-first", "hitl-api-expire-second")
    ]
    assert all(record is not None for record in settled)
    statuses = [record.run.status for record in settled if record is not None]
    assert statuses.count(RunStatus.TIMED_OUT) == 1
    assert statuses.count(RunStatus.PAUSED) == 1


async def test_expiry_endpoint_reports_an_empty_tick(seeded: _Seeded) -> None:
    client, _store, _seed = seeded

    response = client.post("/v1/hitl/expire")

    assert response.status_code == 200
    assert response.json() == {"expired": 0, "run_ids": []}


async def test_expiry_endpoint_only_settles_authorized_workspace_projects(
    reviewer_client: Any, admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user-triggered expiry tick cannot settle another principal's pause."""
    from services import dag_agents
    from services.workspace_authority import canonical_store_for_tests, set_member

    from maistro.projects.scope import ProjectMembership

    # This test seeds the legacy document-shaped store directly. Bind it to the
    # route only as an explicit test seam; production `_store()` refuses this
    # store and requires the Container's canonical projection.
    store = dag_agents.get_run_store()
    assert isinstance(store, InMemoryDurableRunStore)
    monkeypatch.setattr(dag_agents, "get_canonical_run_store", lambda: store)

    deadline = datetime.now(UTC) - timedelta(minutes=1)
    reviewer_workspace = await create_workspace(
        creator_user_id="admin",
        name="HITL expiry reviewer workspace",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    foreign_workspace = await create_workspace(
        creator_user_id="admin",
        name="HITL expiry foreign workspace",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    await set_member(
        reviewer_workspace.id,
        user_id="hitl-expiry-reviewer",
        role="editor",
    )
    projects = canonical_store_for_tests().project_store
    reviewer_root = await projects.root_for_workspace(reviewer_workspace.id)
    foreign_root = await projects.root_for_workspace(foreign_workspace.id)
    await projects.set_membership(
        ProjectMembership(
            workspace_id=reviewer_workspace.id,
            project_id=reviewer_root.project_id,
            principal_id="hitl-expiry-reviewer",
            grants={"hitl.cancel"},
        )
    )
    reviewer_run_id = "hitl-expiry-authorized"
    foreign_run_id = "hitl-expiry-foreign"
    await store.create(
        _paused_record(
            reviewer_run_id,
            deadline=deadline,
            workspace_id=reviewer_workspace.id,
            project_id=reviewer_root.project_id,
        )
    )
    await store.create(
        _paused_record(
            foreign_run_id,
            deadline=deadline,
            workspace_id=foreign_workspace.id,
            project_id=foreign_root.project_id,
        )
    )
    try:
        reviewer_response = reviewer_client.post("/v1/hitl/expire?limit=10")
        assert reviewer_response.status_code == 200
        assert reviewer_response.json() == {"expired": 1, "run_ids": [reviewer_run_id]}
        reviewer = await store.get(reviewer_run_id)
        foreign = await store.get(foreign_run_id)
        assert reviewer is not None and reviewer.run.status is RunStatus.TIMED_OUT
        assert foreign is not None and foreign.run.status is RunStatus.PAUSED

        import stores

        expiry_entries = [
            entry
            for entry in stores.audit_log.values()
            if isinstance(entry, dict) and entry.get("action") == "hitl_expire"
        ]
        assert expiry_entries[-1]["actor"] == "hitl-expiry-reviewer"
        assert foreign_run_id not in str(expiry_entries[-1]["detail"])

        # The second authenticated principal can settle only its own Workspace
        # scope; this also proves the route did not hide the foreign record from
        # the canonical expiry worker rather than mutating it.
        admin_response = admin_client.post("/v1/hitl/expire?limit=10")
        assert admin_response.status_code == 200
        assert admin_response.json() == {"expired": 1, "run_ids": [foreign_run_id]}
        foreign = await store.get(foreign_run_id)
        assert foreign is not None and foreign.run.status is RunStatus.TIMED_OUT
    finally:
        store._rows.pop(reviewer_run_id, None)
        store._rows.pop(foreign_run_id, None)


@pytest.fixture
def workspace_writer_client() -> Iterator[Any]:
    import stores
    from fastapi.testclient import TestClient
    from main import app

    stores.users["scope-user"] = stores.users["user"].model_copy(
        update={
            "id": "scope-user",
            "username": "scope-user",
            "permissions": ["dags.write"],
        }
    )
    client = TestClient(app)
    try:
        assert (
            client.post(
                "/v1/auth/login", json={"username": "scope-user", "password": "testpass"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/v1/auth/elevate",
                json={
                    "password": "testpass",
                    "permissions": ["dags.write"],
                    "task_id": "hitl-expiry-scope-test",
                },
            ).status_code
            == 200
        )
        yield client
    finally:
        stores.users.pop("scope-user", None)


async def test_expiry_endpoint_cannot_timeout_a_foreign_workspace(
    seeded: _Seeded, workspace_writer_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bounded timeout request applies only to canonical member Workspaces."""
    _admin_client, store, _seed = seeded
    mine = await create_workspace(
        creator_user_id="scope-user",
        name="HITL expiry mine",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    other = await create_workspace(
        creator_user_id="other-tenant",
        name="HITL expiry other",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    now = datetime.now(UTC) - timedelta(minutes=1)
    mine_id = "hitl-expiry-scope-mine"
    other_id = "hitl-expiry-scope-other"
    race_id = "hitl-expiry-scope-revoked"
    # Discovery walks authorized Projects (#1110), so the seeded records must
    # live in their Workspace's canonical root Project to be in scope at all.
    from services.workspace_authority import canonical_store_for_tests

    projects = canonical_store_for_tests().project_store
    mine_root = await projects.root_for_workspace(mine.id)
    other_root = await projects.root_for_workspace(other.id)
    await store.create(
        _paused_record(mine_id, deadline=now, workspace_id=mine.id, project_id=mine_root.project_id)
    )
    await store.create(
        _paused_record(
            other_id, deadline=now, workspace_id=other.id, project_id=other_root.project_id
        )
    )
    try:
        response = workspace_writer_client.post("/v1/hitl/expire?limit=10")

        assert response.status_code == 200
        assert response.json() == {"expired": 1, "run_ids": [mine_id]}
        mine_record = await store.get(mine_id)
        other_record = await store.get(other_id)
        assert mine_record is not None and mine_record.run.status is RunStatus.TIMED_OUT
        assert other_record is not None and other_record.run.status is RunStatus.PAUSED

        # The same two-Workspace boundary applies after the local timeout has
        # won a race: a late answer or cancel cannot settle the foreign pause.
        assert (
            workspace_writer_client.post(
                f"/v1/hitl/{other_id}/ask/answer", json={"answer": "late"}
            ).status_code
            == 404
        )
        assert workspace_writer_client.post(f"/v1/hitl/{other_id}/ask/cancel").status_code == 404
        other_record = await store.get(other_id)
        assert other_record is not None and other_record.run.status is RunStatus.PAUSED

        import routes.hitl as hitl_routes

        await store.create(
            _paused_record(
                race_id, deadline=now, workspace_id=mine.id, project_id=mine_root.project_id
            )
        )

        async def revoked_membership(_user_id: str, _workspace_id: str) -> bool:
            return False

        monkeypatch.setattr(hitl_routes, "is_member", revoked_membership)
        response = workspace_writer_client.post("/v1/hitl/expire?limit=10")
        assert response.json() == {"expired": 0, "run_ids": []}
        race_record = await store.get(race_id)
        assert race_record is not None and race_record.run.status is RunStatus.PAUSED
    finally:
        store._rows.pop(mine_id, None)
        store._rows.pop(other_id, None)
        store._rows.pop(race_id, None)


def test_settlement_endpoints_keep_the_existing_dags_write_scope(authed_client: Any) -> None:
    assert authed_client.post("/v1/hitl/expire").status_code == 403
    assert authed_client.post("/v1/hitl/no-run/ask/cancel").status_code == 403
