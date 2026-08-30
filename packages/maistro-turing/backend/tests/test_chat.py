from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.runs.model import RunStatus

pytestmark = [pytest.mark.contract("behavioral")]


def _await(coro: Any) -> Any:
    return asyncio.run(coro)


def test_chat_requires_auth(client):
    assert client.post("/v1/chat", json={"message": "hi"}).status_code == 401


def test_empty_message_rejected(authed_client):
    assert authed_client.post("/v1/chat", json={"message": "  "}).status_code == 400


def test_chat_with_fake_provider_has_canonical_execution_evidence(authed_client, monkeypatch):
    # The dev provider bridge has no LLM client; inject a fake so the real
    # TuringChatSession path runs end-to-end under canonical execution.
    from ..execution import get_execution_plane
    from ..state import get_state

    st = get_state()
    monkeypatch.setattr(st.provider, "complete", lambda *a, **k: "hello from turing", raising=True)

    r = authed_client.post("/v1/chat", json={"message": "hey"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "hello from turing"
    assert body["session_id"]
    assert body["run_id"]

    plane = get_execution_plane()
    run = _await(plane.run_store.get_run(body["run_id"]))
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.actor_principal_id == "user"
    assert run.provenance["product"] == "turing"
    assert run.provenance["session_id"] == body["session_id"]

    workspaces = _await(plane.workspace_store.list_for_user("user"))
    assert len(workspaces) == 1
    root = _await(plane.project_store.root_for_workspace(workspaces[0].workspace_id))
    assert run.workspace_id == workspaces[0].workspace_id
    assert run.project_id == root.project_id

    node_runs = _await(plane.run_store.list_node_runs(run.run_id))
    assert len(node_runs) == 1
    assert node_runs[0].node_id == "turing-chat-turn"
    assert node_runs[0].status is RunStatus.COMPLETED
    assert node_runs[0].result == {"reply": "hello from turing"}
    attempts = _await(plane.run_store.list_attempts(node_runs[0].node_run_id))
    assert len(attempts) == 1


def test_chat_without_llm_returns_503_and_failed_canonical_run(authed_client):
    # No LLM client wired: the domain exception is captured by the canonical
    # Attempt/NodeRun/Run path before the HTTP route projects failure as 503.
    from ..execution import get_execution_plane

    r = authed_client.post("/v1/chat", json={"message": "hey"})
    assert r.status_code == 503

    plane = get_execution_plane()
    failed = _await(plane.run_store.list_by_status(RunStatus.FAILED, limit=10))
    assert len(failed) == 1
    node_runs = _await(plane.run_store.list_node_runs(failed[0].run_id))
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.FAILED
    attempts = _await(plane.run_store.list_attempts(node_runs[0].node_run_id))
    assert len(attempts) == 1


def test_each_turn_gets_a_new_run_without_minting_a_new_workspace(authed_client, monkeypatch):
    from ..execution import get_execution_plane
    from ..state import get_state

    monkeypatch.setattr(
        get_state().provider,
        "complete",
        lambda *a, **k: "hello from turing",
        raising=True,
    )

    first = authed_client.post("/v1/chat", json={"message": "first"})
    assert first.status_code == 200
    second = authed_client.post(
        "/v1/chat",
        json={"message": "second", "session_id": first.json()["session_id"]},
    )
    assert second.status_code == 200
    assert second.json()["run_id"] != first.json()["run_id"]

    plane = get_execution_plane()
    first_run = _await(plane.run_store.get_run(first.json()["run_id"]))
    second_run = _await(plane.run_store.get_run(second.json()["run_id"]))
    assert first_run is not None and second_run is not None
    assert first_run.workspace_id == second_run.workspace_id
    assert first_run.project_id == second_run.project_id
    assert len(_await(plane.workspace_store.list_for_user("user"))) == 1


def test_reply_projection_rejects_missing_canonical_node_results():
    from ..routes.chat import _reply_from_record

    empty_record: Any = SimpleNamespace(node_runs=[])
    with pytest.raises(RuntimeError, match="produced no NodeRun"):
        _reply_from_record(empty_record)

    missing_reply_record: Any = SimpleNamespace(
        node_runs=[SimpleNamespace(result={"unexpected": "value"})]
    )
    with pytest.raises(RuntimeError, match="produced no reply"):
        _reply_from_record(missing_reply_record)


def test_turing_execution_plane_rejects_unknown_node_resolution(monkeypatch):
    from .. import execution as execution_module

    async def reject_unknown_node(graph: Any, **kwargs: Any) -> Any:
        resolver = kwargs["node_resolver"]
        resolver("unexpected-node", graph)
        raise AssertionError("unknown node resolution should fail closed")

    monkeypatch.setattr(execution_module, "run_durable_graph", reject_unknown_node)
    session: Any = object()
    plane = execution_module.TuringExecutionPlane()

    with pytest.raises(KeyError, match="unknown Turing canonical node 'unexpected-node'"):
        _await(
            plane.run_chat(
                session=session,
                user_id="user",
                session_id="session",
                message="hello",
            )
        )
