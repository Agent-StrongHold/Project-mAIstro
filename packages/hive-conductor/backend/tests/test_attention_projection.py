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
def run_store():
    from services.dag_agents import get_run_store

    store = get_run_store()
    before = set(store._rows)
    yield store
    for run_id in set(store._rows) - before:
        store._rows.pop(run_id, None)


def _ids(body: dict[str, Any]) -> list[str]:
    return [item["source_id"] for item in body["items"]]


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
        "highest_class": "time_sensitive",
        "rising": ["att-due/ask"],
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
    assert body["summary"] == {"counts_by_class": {}, "highest_class": None, "rising": []}


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
    run = await container.run_store.create_run(graph)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await container.run_store.transition_run(run.run_id, status)
    await container.run_store.transition_run(
        run.run_id, RunStatus.FAILED, error="upstream tool refused the request"
    )
    projection = get_dag_run_store()
    await projection.start_run(run_id=run.run_id, canonical_run_id=run.run_id, workspace_id=ws)
    await projection.finish_run(run.run_id, status="failed")
    await projection.start_run(run_id="att-other-failed", workspace_id=other)
    await projection.finish_run("att-other-failed", status="failed")
    await projection.start_run(run_id="att-completed", workspace_id=ws)
    await projection.finish_run("att-completed", status="completed")

    body = await list_attention("admin", ws, now=_NOW)

    assert body is not None
    (item,) = [i for i in body["items"] if i["source_kind"] == "failed_run"]
    assert item["source_id"] == run.run_id
    assert item["workspace_id"] == ws
    assert item["attention_class"] == "queued"
    assert item["evidence"]["error"] == "upstream tool refused the request"
    assert item["reason"] == f"Run {run.run_id} failed: upstream tool refused the request"
    assert item["answer_href"] is None


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
