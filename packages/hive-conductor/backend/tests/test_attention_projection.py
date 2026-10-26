"""Workspace Attention is a read-time projection over canonical sources (#1049).

Driven against the app's real durable run store and the canonical Workspace
authority, not mocks: the contract is that Attention classifies what those
owners already hold, discloses it only inside the caller's Workspace, and
writes nothing back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from services.attention import list_attention
from services.workspace_authority import create_workspace

from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import (
    PAUSE_AWAITING_HUMAN_ANSWER,
    PAUSE_AWAITING_HUMAN_APPROVAL,
)
from maistro.runs.lifecycle import transition_node_run, transition_run
from maistro.runs.model import GraphSnapshot, NodeRun, Run, RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _paused_record(
    run_id: str,
    *,
    workspace_id: str,
    kind: str = "hitl",
    paused_reason: str = PAUSE_AWAITING_HUMAN_ANSWER,
    deadline: datetime | None = None,
    created_at: datetime | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> DurableRunRecord:
    """A Run paused on one node, shaped as the durable executor persists it."""
    graph = Graph(
        workspace_id=workspace_id,
        project_id="project-attention",
        name="attention",
        nodes=[Node(node_id="ask", node_type="human.ask_question")],
    )
    run = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    if created_at is not None:
        run = run.model_copy(update={"created_at": created_at})
    for status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED):
        run = transition_run(run, status)
    node_run = NodeRun(run_id=run_id, node_id="ask", ordinal=1)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED):
        node_run = transition_node_run(node_run, status)
    metadata = {"paused_reason": paused_reason, "question": f"{run_id}?"}
    metadata.update(extra_metadata or {})
    state = GraphExecutionState(
        run_id=run_id,
        active_node_ids=("ask",),
        blackboard_snapshot={},
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {
                "ask": {
                    "kind": kind,
                    "metadata": metadata,
                    "resume_at": deadline.isoformat() if deadline else None,
                }
            },
        },
    )
    return DurableRunRecord(run=run, graph_state=state, node_runs=(node_run,), version=1)


async def _workspace(owner: str, name: str) -> str:
    workspace = await create_workspace(
        creator_user_id=owner,
        name=name,
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    return workspace.id


@pytest.fixture
def run_store(monkeypatch):
    """Document-shaped historical records are explicit read-only test input."""
    from services import dag_agents

    from maistro.graph.durable_runs import InMemoryDurableRunStore

    store = InMemoryDurableRunStore()
    monkeypatch.setattr(dag_agents, "get_run_store", lambda: store)
    return store


def _ids(body: dict[str, Any]) -> list[str]:
    return [item["source_id"] for item in body["items"]]


async def test_attention_answers_when_the_hitl_spine_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Standalone / e2e Conductor has no graph spine — Attention must still 200.

    HITL pauses are unavailable (honest flag); failed-Run projections may still
    populate. A missing spine must not turn the Attention door into a 500.
    """
    from services import dag_agents
    from services.dag_agents import CanonicalGraphUnavailable

    def _refuse() -> None:
        raise CanonicalGraphUnavailable("canonical graph execution spine is unavailable")

    monkeypatch.setattr(dag_agents, "get_run_store", _refuse)
    ws = await _workspace("admin", "Attention standalone")
    body = await list_attention("admin", ws, now=_NOW)
    assert body is not None
    assert body["workspace_id"] == ws
    assert body["items"] == []
    assert body["summary"]["hitl_unavailable"] is True
    assert body["summary"]["truncated"] is False


async def test_each_member_sees_only_their_own_workspace(run_store) -> None:
    ws_admin = await _workspace("admin", "Attention admin")
    ws_user = await _workspace("user", "Attention user")
    await run_store.create(_paused_record("att-admin", workspace_id=ws_admin))
    await run_store.create(_paused_record("att-user", workspace_id=ws_user))

    admin_view = await list_attention("admin", ws_admin, now=_NOW)
    user_view = await list_attention("user", ws_user, now=_NOW)

    assert admin_view is not None and user_view is not None
    assert _ids(admin_view) == ["att-admin/ask"]
    assert _ids(user_view) == ["att-user/ask"]
    assert admin_view["items"][0]["workspace_id"] == ws_admin
    assert admin_view["summary"]["hitl_unavailable"] is False
    # A non-member gets exactly what a Workspace that does not exist gets.
    assert await list_attention("user", ws_admin, now=_NOW) is None
    assert await list_attention("user", "ws-does-not-exist", now=_NOW) is None


async def test_a_near_deadline_outranks_an_older_undated_question(run_store) -> None:
    ws = await _workspace("admin", "Attention ranking")
    await run_store.create(
        _paused_record(
            "att-ancient",
            workspace_id=ws,
            created_at=_NOW - timedelta(days=400),
        )
    )
    await run_store.create(
        _paused_record("att-due", workspace_id=ws, deadline=_NOW + timedelta(hours=2))
    )
    await run_store.create(
        _paused_record("att-later", workspace_id=ws, deadline=_NOW + timedelta(days=30))
    )

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None
    assert _ids(body) == ["att-due/ask", "att-later/ask", "att-ancient/ask"]
    due, later, ancient = body["items"]
    assert due["attention_class"] == "time_sensitive"
    assert due["reason"].startswith("Answer due by 2026-09-25T14:00:00+00:00")
    assert due["evidence"]["deadline"] == "2026-09-25T14:00:00+00:00"
    # A deadline outside the horizon is evidence, not escalation.
    assert later["attention_class"] == "queued"
    # Four hundred days of waiting is still just a queued question.
    assert ancient["attention_class"] == "queued"
    assert ancient["reason"] == "Run att-ancient is waiting on your answer at node ask"
    assert [item["rank"] for item in body["items"]] == [1, 2, 3]
    assert ancient["answer_href"] == "/v1/hitl/att-ancient/ask/answer"
    assert body["summary"] == {
        "counts_by_class": {"time_sensitive": 1, "queued": 2},
        "counts_by_interruption": {"popup": 1, "queued": 2},
        "highest_class": "time_sensitive",
        "rising": ["att-due/ask"],
        "waiting_quality": {"count": 0, "valuable_source_ids": []},
        "truncated": False,
        "hitl_unavailable": False,
        "dismissed_count": 0,
    }

    # The horizon is configurable, and widening it is the only thing that
    # promotes the later deadline.
    wide = await list_attention("admin", ws, now=_NOW, horizon=timedelta(days=31))
    assert wide is not None
    assert [item["attention_class"] for item in wide["items"]] == [
        "time_sensitive",
        "time_sensitive",
        "queued",
    ]


async def test_an_approval_pause_is_a_decision_naming_the_blocked_run(run_store) -> None:
    ws = await _workspace("admin", "Attention approval")
    await run_store.create(
        _paused_record(
            "att-approve",
            workspace_id=ws,
            paused_reason=PAUSE_AWAITING_HUMAN_APPROVAL,
            extra_metadata={"approval_request_id": "apr-1"},
        )
    )

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None
    (item,) = body["items"]
    assert item["source_kind"] == "hitl_node_run"
    assert item["attention_class"] == "queued"
    assert item["reason"] == "Run att-approve is blocked awaiting your approval at node ask"
    assert item["evidence"]["paused_reason"] == PAUSE_AWAITING_HUMAN_APPROVAL
    assert item["evidence"]["payload"]["approval_request_id"] == "apr-1"


async def test_a_long_old_backlog_cannot_push_out_a_near_deadline(run_store) -> None:
    """The page ceiling applies after ordering, never to the oldest records first."""
    ws = await _workspace("admin", "Attention backlog")
    for index in range(205):
        await run_store.create(
            _paused_record(
                f"att-old-{index:03d}",
                workspace_id=ws,
                created_at=_NOW - timedelta(days=300, minutes=index),
            )
        )
    await run_store.create(
        _paused_record("att-urgent", workspace_id=ws, deadline=_NOW + timedelta(hours=1))
    )

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None
    assert len(body["items"]) == 200
    assert body["items"][0]["source_id"] == "att-urgent/ask"
    assert body["summary"] == {
        "counts_by_class": {"time_sensitive": 1, "queued": 205},
        "counts_by_interruption": {"popup": 1, "queued": 205},
        "highest_class": "time_sensitive",
        "rising": ["att-urgent/ask"],
        "waiting_quality": {"count": 0, "valuable_source_ids": []},
        "truncated": True,
        "hitl_unavailable": False,
        "dismissed_count": 0,
    }


async def test_an_overdue_pause_offers_no_answer(run_store) -> None:
    """The store refuses answers past the deadline; Attention must not offer one."""
    ws = await _workspace("admin", "Attention overdue")
    await run_store.create(
        _paused_record("att-overdue", workspace_id=ws, deadline=_NOW - timedelta(minutes=5))
    )

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None
    (item,) = body["items"]
    assert item["attention_class"] == "queued"
    assert item["answer_href"] is None
    assert item["reason"].startswith(
        "Answer deadline passed at 2026-09-25T11:55:00+00:00; awaiting expiry."
    )
    assert body["summary"]["rising"] == []


async def test_membership_revoked_mid_scan_withholds_payloads(
    run_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The up-front check is not the disclosure decision; each record is rechecked."""
    import services.attention as attention_mod
    from services import workspace_authority

    ws = await _workspace("user", "Attention revoked")
    await workspace_authority.set_member(ws, user_id="admin", role="editor")
    await run_store.create(_paused_record("att-revoked", workspace_id=ws))
    real_is_member = workspace_authority.is_member
    calls = 0

    async def revoke_after_admission(user_id: str, workspace_id: str | None) -> bool:
        nonlocal calls
        calls += 1
        allowed = await real_is_member(user_id, workspace_id)
        if calls == 1:
            await workspace_authority.remove_member(ws, user_id="admin")
        return allowed

    monkeypatch.setattr(attention_mod, "is_member", revoke_after_admission)

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None
    assert body["items"] == []
    assert calls >= 2


async def test_a_naive_clock_is_refused(run_store) -> None:
    ws = await _workspace("admin", "Attention naive clock")
    with pytest.raises(ValueError, match="timezone"):
        await list_attention("admin", ws, now=datetime(2026, 9, 25, 12, 0))


async def test_a_machine_wait_is_not_attention(run_store) -> None:
    ws = await _workspace("admin", "Attention machine")
    await run_store.create(
        _paused_record(
            "att-timer", workspace_id=ws, kind="wait", deadline=_NOW + timedelta(minutes=5)
        )
    )

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None
    assert body["items"] == []
    assert body["summary"] == {
        "counts_by_class": {},
        "counts_by_interruption": {},
        "highest_class": None,
        "rising": [],
        "waiting_quality": {"count": 0, "valuable_source_ids": []},
        "truncated": False,
        "hitl_unavailable": False,
        "dismissed_count": 0,
    }


async def test_attention_finds_the_workspace_pause_behind_a_full_page_of_foreign_pauses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The #1109 repair's Attention regression: Workspace-wide, behind one
    full walk page of other tenants' human pauses, this Workspace's pause is
    still found and `truncated` stays False. Driven against the canonical
    store, where Workspace scope filters the assembled page — the shape that
    read as an empty projection page and a false "ran out" before the
    repair. `MAX_PENDING_SCAN_RECORDS` is pulled down to the page size so the
    foreign prefix is a full page at Attention's own limit; without the
    repair the walk answered empty here and called it complete."""
    from services import attention as attention_module
    from services import dag_agents

    from maistro.graph.durable_runs import CanonicalDurableRunStore
    from maistro.graph.durable_runs.continuation import InMemoryGraphContinuationStore
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore

    projects = InMemoryProjectScopeStore()
    spine = InMemoryRunStore(project_store=projects)
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(spine, continuations)
    monkeypatch.setattr(dag_agents, "get_canonical_run_store", lambda: store)
    monkeypatch.setattr(attention_module, "MAX_PENDING_SCAN_RECORDS", 100)

    ws = await _workspace("admin", "Attention behind foreign page")
    foreign_ws = await _workspace("someone-else", "Attention foreign page")
    own_project = (await projects.create_root(ws)).project_id
    foreign_project = (await projects.create_root(foreign_ws)).project_id

    async def _plant_canonical_pause(run_id: str, *, workspace_id: str, project_id: str) -> str:
        """One human-paused Run on the canonical spine, projected beside it."""
        from maistro.graph.durable_runs.continuation import GraphContinuation

        graph = Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name="attention",
            nodes=[Node(node_id="ask", node_type="human.ask_question")],
        )
        admitted = await spine.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        await spine.transition_run(admitted.run_id, RunStatus.RUNNING)
        await spine.transition_run(admitted.run_id, RunStatus.PAUSED)
        node_run = await spine.create_node_run(admitted.run_id, node_id="ask")
        await spine.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        await spine.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        await spine.transition_node_run(node_run.node_run_id, RunStatus.PAUSED)
        run = await spine.get_run(admitted.run_id)
        assert run is not None
        node_runs = tuple(await spine.list_node_runs(admitted.run_id))
        state = GraphExecutionState(
            run_id=admitted.run_id,
            active_node_ids=("ask",),
            blackboard_snapshot={},
            metadata={
                "initial_inputs": {},
                "hitl_answers": {},
                "pauses": {
                    "ask": {
                        "kind": "hitl",
                        "metadata": {
                            "paused_reason": PAUSE_AWAITING_HUMAN_ANSWER,
                            "question": f"{run_id}?",
                        },
                        "resume_at": None,
                    }
                },
            },
        )
        await continuations.create(
            GraphContinuation.of(
                DurableRunRecord(run=run, graph_state=state, node_runs=node_runs, version=1)
            )
        )
        return admitted.run_id

    for index in range(100):
        await _plant_canonical_pause(
            f"att-foreign-{index:03d}",
            workspace_id=foreign_ws,
            project_id=foreign_project,
        )
    mine_run_id = await _plant_canonical_pause(
        "att-behind", workspace_id=ws, project_id=own_project
    )

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None
    assert _ids(body) == [f"{mine_run_id}/ask"]
    assert body["summary"]["truncated"] is False


async def test_listing_attention_writes_nothing(run_store) -> None:
    ws = await _workspace("admin", "Attention read-only")
    await run_store.create(
        _paused_record("att-readonly", workspace_id=ws, deadline=_NOW + timedelta(hours=1))
    )
    before = run_store._rows["att-readonly"].model_dump_json()

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None and _ids(body) == ["att-readonly/ask"]
    assert run_store._rows["att-readonly"].model_dump_json() == before


async def test_a_failed_run_is_queued_with_its_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure's evidence is the canonical Run's own error."""
    import services.engine as engine_mod
    from services.dag_run_store import get_dag_run_store

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    monkeypatch.setattr(
        engine_mod.get_engine(), "_agent_port", SimpleNamespace(container=container)
    )
    ws = await _workspace("admin", "Attention failure")
    other = await _workspace("admin", "Attention failure elsewhere")
    root = await container.project_scope_store.root_for_workspace(ws)
    graph = Graph(
        workspace_id=ws,
        project_id=root.project_id,
        name="failing",
        nodes=[Node(node_id="only", node_type="transform.alias_keys")],
    )
    run = await container.run_store.create_run(
        graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await container.run_store.transition_run(run.run_id, status)
    await container.run_store.transition_run(
        run.run_id, RunStatus.FAILED, error="upstream tool refused the request"
    )
    projection = get_dag_run_store()
    seeded = [run.run_id, "att-other-failed", "att-completed"]
    try:
        await _seed_projection(projection, run.run_id, ws, other)
        body = await list_attention("admin", ws, now=_NOW)
    finally:
        for run_id in seeded:
            projection._runs.pop(run_id, None)
            projection._forget(run_id)
            if run_id in projection._order:
                projection._order.remove(run_id)

    assert body is not None
    (item,) = [i for i in body["items"] if i["source_kind"] == "failed_run"]
    assert item["source_id"] == run.run_id
    assert item["workspace_id"] == ws
    assert item["attention_class"] == "queued"
    assert item["evidence"]["error"] == "upstream tool refused the request"
    assert item["reason"] == f"Run {run.run_id} failed: upstream tool refused the request"
    assert item["answer_href"] is None


async def _seed_projection(projection: Any, run_id: str, ws: str, other: str) -> None:
    await projection.start_run(run_id=run_id, canonical_run_id=run_id, workspace_id=ws)
    await projection.finish_run(run_id, status="failed")
    await projection.start_run(run_id="att-other-failed", workspace_id=other)
    await projection.finish_run("att-other-failed", status="failed")
    await projection.start_run(run_id="att-completed", workspace_id=ws)
    await projection.finish_run("att-completed", status="completed")


async def test_route_scopes_attention_to_members(admin_client, authed_client, run_store) -> None:
    ws_admin = await _workspace("admin", "Attention route admin")
    ws_user = await _workspace("user", "Attention route user")
    await run_store.create(_paused_record("att-route-admin", workspace_id=ws_admin))
    await run_store.create(_paused_record("att-route-user", workspace_id=ws_user))

    response = admin_client.get(f"/v1/workspaces/{ws_admin}/attention")
    assert response.status_code == 200
    assert _ids(response.json()) == ["att-route-admin/ask"]

    foreign = admin_client.get(f"/v1/workspaces/{ws_user}/attention")
    missing = admin_client.get("/v1/workspaces/ws-no-such-thing/attention")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()

    # The items carry the question a paused node is asking, so reading them
    # takes the scope `/v1/hitl/pending` takes, even for the owner.
    unscoped = authed_client.get(f"/v1/workspaces/{ws_user}/attention")
    assert unscoped.status_code == 403
    # Scope is checked before membership, so an unscoped caller cannot probe
    # which Workspaces exist.
    unscoped_missing = authed_client.get("/v1/workspaces/ws-no-such-thing/attention")
    assert unscoped_missing.status_code == 403


async def test_dismiss_hides_item_and_counts_preference(run_store) -> None:
    """#1049: defer/dismiss is preference evidence — GET filters the source id
    and reports dismissed_count; another Workspace is unaffected."""
    from services.attention import clear_dismissal, list_attention, record_dismissal

    ws = await _workspace("admin", "Attention dismiss")
    other = await _workspace("admin", "Attention dismiss other")
    await run_store.create(_paused_record("att-keep", workspace_id=ws))
    await run_store.create(_paused_record("att-hide", workspace_id=ws))
    await run_store.create(_paused_record("att-other-ws", workspace_id=other))

    record_dismissal(ws, "hitl_node_run", "att-hide/ask", actor="admin", action="dismiss")

    body = await list_attention("admin", ws, now=_NOW)
    assert body is not None
    assert _ids(body) == ["att-keep/ask"]
    assert body["summary"]["dismissed_count"] == 1

    # Same source id in another Workspace is not filtered by this preference.
    other_body = await list_attention("admin", other, now=_NOW)
    assert other_body is not None
    assert _ids(other_body) == ["att-other-ws/ask"]
    assert other_body["summary"]["dismissed_count"] == 0

    clear_dismissal(ws, "hitl_node_run", "att-hide/ask")
    restored = await list_attention("admin", ws, now=_NOW)
    assert restored is not None
    assert set(_ids(restored)) == {"att-keep/ask", "att-hide/ask"}
    assert restored["summary"]["dismissed_count"] == 0


async def test_defer_and_dismiss_routes_are_member_scoped(
    admin_client, authed_client, run_store
) -> None:
    """POST/DELETE dismiss require membership + dags.write like GET."""
    from services.attention import dismissal_store

    ws_admin = await _workspace("admin", "Attention dismiss route")
    ws_user = await _workspace("user", "Attention dismiss route user")
    await run_store.create(_paused_record("att-dismiss-route", workspace_id=ws_admin))

    ok = admin_client.post(
        f"/v1/workspaces/{ws_admin}/attention/dismiss",
        json={
            "sourceKind": "hitl_node_run",
            "sourceId": "att-dismiss-route/ask",
            "action": "defer",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True
    assert ok.json()["action"] == "defer"

    filtered = admin_client.get(f"/v1/workspaces/{ws_admin}/attention")
    assert filtered.status_code == 200
    assert "att-dismiss-route/ask" not in _ids(filtered.json())
    assert filtered.json()["summary"]["dismissed_count"] == 1

    foreign = admin_client.post(
        f"/v1/workspaces/{ws_user}/attention/dismiss",
        json={"sourceKind": "hitl", "sourceId": "x", "action": "dismiss"},
    )
    missing = admin_client.post(
        "/v1/workspaces/ws-no-such-thing/attention/dismiss",
        json={"sourceKind": "hitl", "sourceId": "x", "action": "dismiss"},
    )
    assert foreign.status_code == missing.status_code == 404

    unscoped = authed_client.post(
        f"/v1/workspaces/{ws_admin}/attention/dismiss",
        json={"sourceKind": "hitl_node_run", "sourceId": "x", "action": "dismiss"},
    )
    assert unscoped.status_code == 403
    assert "dags.write" in unscoped.json()["detail"]

    cleared = admin_client.delete(
        f"/v1/workspaces/{ws_admin}/attention/dismiss",
        params={"sourceKind": "hitl_node_run", "sourceId": "att-dismiss-route/ask"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True
    # Preference row gone from the JsonStore.
    leftover = f"{ws_admin}:hitl_node_run:att-dismiss-route/ask"
    assert leftover not in dismissal_store

    # DELETE carries the same dags.write + membership gates as POST (not the
    # middleware workspaces.write gate — Attention dismiss is preference
    # evidence, exempted like Home adaptive dismiss).
    unscoped_del = authed_client.delete(
        f"/v1/workspaces/{ws_admin}/attention/dismiss",
        params={"sourceKind": "hitl_node_run", "sourceId": "x"},
    )
    assert unscoped_del.status_code == 403
    assert "dags.write" in unscoped_del.json()["detail"]
    foreign_del = admin_client.delete(
        f"/v1/workspaces/{ws_user}/attention/dismiss",
        params={"sourceKind": "hitl_node_run", "sourceId": "x"},
    )
    missing_del = admin_client.delete(
        "/v1/workspaces/ws-no-such-thing/attention/dismiss",
        params={"sourceKind": "hitl_node_run", "sourceId": "x"},
    )
    assert foreign_del.status_code == missing_del.status_code == 404


async def test_dismiss_route_maps_value_error_to_400(
    admin_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pydantic usually blocks blank ids; a service ValueError still becomes 400."""
    from routes import attention as attention_routes

    ws = await _workspace("admin", "Attention dismiss value-error")

    def _boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise ValueError("action must be dismiss or defer")

    # Route binds the symbol at import time — patch the routes module.
    monkeypatch.setattr(attention_routes, "record_dismissal", _boom)
    refused = admin_client.post(
        f"/v1/workspaces/{ws}/attention/dismiss",
        json={
            "sourceKind": "hitl_node_run",
            "sourceId": "att-ve/ask",
            "action": "dismiss",
        },
    )
    assert refused.status_code == 400
    assert "dismiss or defer" in refused.json()["detail"]


def test_dismissal_helpers_reject_blank_ids_and_unknown_actions() -> None:
    from services.attention import (
        clear_dismissal,
        dismissal_store,
        dismissed_source_ids,
        record_dismissal,
    )

    with pytest.raises(ValueError, match="source_kind and source_id"):
        record_dismissal("ws-blank", "", "sid", actor="admin")
    with pytest.raises(ValueError, match="source_kind and source_id"):
        record_dismissal("ws-blank", "kind", "", actor="admin")
    with pytest.raises(ValueError, match="dismiss or defer"):
        record_dismissal("ws-blank", "kind", "sid", actor="admin", action="snooze")

    assert clear_dismissal("ws-absent", "kind", "sid") is False

    # Incomplete store rows are ignored — they never mint a filter key.
    dismissal_store["ws-skip:hitl_node_run:broken"] = {
        "source_kind": "",
        "source_id": "broken",
    }
    dismissal_store["ws-skip:not-a-dict"] = "noise"
    try:
        assert dismissed_source_ids("ws-skip") == set()
    finally:
        dismissal_store.pop("ws-skip:hitl_node_run:broken", None)
        dismissal_store.pop("ws-skip:not-a-dict", None)


async def test_include_dismissed_keeps_items_and_counts(run_store) -> None:
    """``include_dismissed=True`` leaves items visible but still counts them."""
    from services.attention import list_attention, record_dismissal

    ws = await _workspace("admin", "Attention include dismissed")
    await run_store.create(_paused_record("att-keep-inc", workspace_id=ws))
    await run_store.create(_paused_record("att-hide-inc", workspace_id=ws))
    record_dismissal(ws, "hitl_node_run", "att-hide-inc/ask", actor="admin")

    body = await list_attention("admin", ws, now=_NOW, include_dismissed=True)
    assert body is not None
    assert set(_ids(body)) == {"att-keep-inc/ask", "att-hide-inc/ask"}
    assert body["summary"]["dismissed_count"] == 1


def test_priority_ladder_orders_severity_before_proactive() -> None:
    """#1049: severity > time_sensitive > blocking > queued > follow_up > proactive."""
    from services.attention import ATTENTION_CLASSES, _Item

    assert ATTENTION_CLASSES == (
        "severity",
        "time_sensitive",
        "blocking",
        "queued",
        "follow_up",
        "proactive",
    )
    items = [
        _Item("k", "proactive", "ws", "proactive", "p"),
        _Item("k", "severity", "ws", "severity", "s"),
        _Item("k", "queued", "ws", "queued", "q"),
        _Item("k", "follow_up", "ws", "follow_up", "f"),
        _Item("k", "blocking", "ws", "blocking", "b"),
        _Item(
            "k",
            "time_sensitive",
            "ws",
            "time_sensitive",
            "t",
            deadline=_NOW + timedelta(hours=1),
        ),
    ]
    items.sort(key=_Item.sort_key)
    assert [i.attention_class for i in items] == list(ATTENTION_CLASSES)


def test_age_alone_does_not_escalate_class() -> None:
    """Escalation needs evidence other than elapsed time (#1049)."""
    from services.attention import INTERRUPTION_FOR_CLASS, _Item

    ancient = _Item(
        "hitl_node_run",
        "old/ask",
        "ws",
        "queued",
        "still queued after months",
        evidence={"paused_at": (_NOW - timedelta(days=400)).isoformat()},
    )
    assert ancient.attention_class == "queued"
    assert INTERRUPTION_FOR_CLASS[ancient.attention_class] == "queued"
    # No automatic promotion helper keyed only on age exists on the item.
    assert "escalated_because_old" not in ancient.evidence


async def test_messages_and_optimizer_map_into_attention_classes(run_store) -> None:
    """MessageBoard + OptimizationInbox MERGE: class + interruption mapping."""
    import stores
    from services.attention import list_attention, set_message_rows_provider

    ws = await _workspace("admin", "Attention merge sources")
    other = await _workspace("admin", "Attention merge other")
    planted = {
        "msg-crit": {
            "id": "msg-crit",
            "from_agent": "Warden",
            "to": "admin",
            "subject": "Critical finding",
            "body": "needs eyes",
            "priority": "critical",
            "read": False,
            "category": "security",
            "created_at": _NOW.isoformat(),
        },
        "msg-warn": {
            "id": "msg-warn",
            "from_agent": "Quota",
            "to": "admin",
            "subject": "Quota warning",
            "body": "75%",
            "priority": "warning",
            "read": False,
            "category": "quota",
            "created_at": _NOW.isoformat(),
        },
        "msg-info": {
            "id": "msg-info",
            "from_agent": "DreamLoop",
            "to": "all",
            "subject": "Idea",
            "body": "optional",
            "priority": "info",
            "read": False,
            "category": "mission",
            "created_at": _NOW.isoformat(),
        },
        "msg-read": {
            "id": "msg-read",
            "from_agent": "System",
            "to": "admin",
            "subject": "Already read",
            "body": "skip",
            "priority": "critical",
            "read": True,
            "category": "system",
            "created_at": _NOW.isoformat(),
        },
    }
    proposals = {
        "prop-here": {
            "id": "prop-here",
            "dag_id": "dag-a",
            "kind": "topology_mutation",
            "rationale": "cheaper model",
            "priority_score": 0.8,
            "decision": "pending",
            "workspace_id": ws,
            "field_path": "nodes.0.model",
            "class": "propose",
            "blocked_by_edit_lock": False,
            "topology_proposal": {
                "kind": "swap_model",
                "target_node_id": "n1",
                "from_value": "m-a",
                "to_value": "m-strong",
                "expected_improvement": "higher quality",
            },
        },
        "prop-elsewhere": {
            "id": "prop-elsewhere",
            "dag_id": "dag-b",
            "kind": "retry_count_tune",
            "rationale": "other ws",
            "priority_score": 0.9,
            "decision": "pending",
            "workspace_id": other,
            "field_path": "nodes.0.retry",
            "class": "propose",
            "blocked_by_edit_lock": False,
        },
        "prop-decided": {
            "id": "prop-decided",
            "dag_id": "dag-a",
            "kind": "prompt_rewrite",
            "rationale": "done",
            "priority_score": 0.7,
            "decision": "accepted",
            "workspace_id": ws,
            "field_path": "nodes.0.prompt",
            "class": "propose",
            "blocked_by_edit_lock": False,
        },
    }
    prior_msgs = {k: stores.messages[k] for k in list(stores.messages.keys())}
    prior_props = {
        k: stores.optimizer_proposals[k] for k in list(stores.optimizer_proposals.keys())
    }
    try:
        for key in list(stores.messages.keys()):
            stores.messages.pop(key)
        for key in list(stores.optimizer_proposals.keys()):
            stores.optimizer_proposals.pop(key)
        for key, row in planted.items():
            stores.messages[key] = row
        for key, row in proposals.items():
            stores.optimizer_proposals[key] = row
        # Mirror main.py's wire: tests call list_attention without booting the app.
        set_message_rows_provider(lambda: list(stores.messages.values()))

        body = await list_attention("admin", ws, now=_NOW)
        assert body is not None
        by_id = {item["source_id"]: item for item in body["items"]}
        assert set(by_id) == {"msg-crit", "msg-warn", "msg-info", "prop-here"}
        assert by_id["msg-crit"]["attention_class"] == "severity"
        assert by_id["msg-crit"]["interruption"] == "blocking"
        assert by_id["msg-crit"]["source_kind"] == "agent_message"
        assert by_id["msg-warn"]["attention_class"] == "queued"
        assert by_id["msg-warn"]["interruption"] == "queued"
        assert by_id["msg-info"]["attention_class"] == "proactive"
        assert by_id["msg-info"]["interruption"] == "waiting"
        assert by_id["prop-here"]["attention_class"] == "proactive"
        assert by_id["prop-here"]["interruption"] == "waiting"
        assert by_id["prop-here"]["source_kind"] == "optimizer_proposal"
        assert by_id["prop-here"]["evidence"]["accept_href"].endswith("/accept")
        assert by_id["prop-here"]["evidence"]["topology_proposal"] == {
            "kind": "swap_model",
            "target_node_id": "n1",
            "from_value": "m-a",
            "to_value": "m-strong",
            "expected_improvement": "higher quality",
        }
        # Priority order: severity before queued before proactive.
        assert _ids(body) == ["msg-crit", "msg-warn", "msg-info", "prop-here"]
        assert body["summary"]["counts_by_interruption"] == {
            "blocking": 1,
            "queued": 1,
            "waiting": 2,
        }
        assert body["summary"]["waiting_quality"]["count"] == 2
        assert "prop-here" in body["summary"]["waiting_quality"]["valuable_source_ids"]

        # Optimizer does not bleed across Workspaces; messages are user-global.
        other_body = await list_attention("admin", other, now=_NOW)
        assert other_body is not None
        other_ids = set(_ids(other_body))
        assert "prop-elsewhere" in other_ids
        assert "prop-here" not in other_ids
        assert {"msg-crit", "msg-warn", "msg-info"} <= other_ids
    finally:
        set_message_rows_provider(None)
        for key in list(stores.messages.keys()):
            stores.messages.pop(key)
        for key, row in prior_msgs.items():
            stores.messages[key] = row
        for key in list(stores.optimizer_proposals.keys()):
            stores.optimizer_proposals.pop(key)
        for key, row in prior_props.items():
            stores.optimizer_proposals[key] = row


async def test_optimizer_workspace_filter_runs_before_list_cap(run_store) -> None:
    """Newer foreign Workspace proposals must not hide this Workspace's pending row.

    ``list_proposals`` caps at 200 after sorting newest-first; filtering by
    Workspace only after that cap would drop an older in-Workspace proposal
    when 200 newer foreign rows fill the page.
    """
    import stores
    from services.attention import list_attention, set_message_rows_provider
    from services.optimizer import list_proposals

    ws = await _workspace("admin", "Attention opt cap ws")
    other = await _workspace("admin", "Attention opt cap other")
    prior_props = {
        k: stores.optimizer_proposals[k] for k in list(stores.optimizer_proposals.keys())
    }
    try:
        for key in list(stores.optimizer_proposals.keys()):
            stores.optimizer_proposals.pop(key)
        # 200 newer pending proposals in the other Workspace (created_at later).
        for i in range(200):
            pid = f"prop-foreign-{i:03d}"
            stores.optimizer_proposals[pid] = {
                "id": pid,
                "dag_id": "dag-b",
                "kind": "model_swap",
                "rationale": "foreign",
                "priority_score": 0.1,
                "decision": "pending",
                "workspace_id": other,
                "created_at": f"2026-09-26T12:{i // 60:02d}:{i % 60:02d}Z",
            }
        stores.optimizer_proposals["prop-local-old"] = {
            "id": "prop-local-old",
            "dag_id": "dag-a",
            "kind": "prompt_rewrite",
            "rationale": "local older",
            "priority_score": 0.9,
            "decision": "pending",
            "workspace_id": ws,
            "created_at": "2026-09-25T12:00:00Z",
            "topology_proposal": {
                "kind": "rewrite_prompt",
                "from_value": "old prompt",
                "to_value": "new prompt",
            },
        }
        set_message_rows_provider(lambda: [])

        scoped = list_proposals(decision="pending", workspace_id=ws, limit=200)
        assert [p["id"] for p in scoped] == ["prop-local-old"]

        unscoped = list_proposals(decision="pending", limit=200)
        assert "prop-local-old" not in {p["id"] for p in unscoped}
        assert len(unscoped) == 200

        body = await list_attention("admin", ws, now=_NOW)
        assert body is not None
        by_id = {item["source_id"]: item for item in body["items"]}
        assert "prop-local-old" in by_id
        assert by_id["prop-local-old"]["evidence"]["topology_proposal"]["from_value"] == (
            "old prompt"
        )
        assert by_id["prop-local-old"]["evidence"]["topology_proposal"]["to_value"] == (
            "new prompt"
        )
    finally:
        set_message_rows_provider(None)
        for key in list(stores.optimizer_proposals.keys()):
            stores.optimizer_proposals.pop(key)
        for key, row in prior_props.items():
            stores.optimizer_proposals[key] = row
