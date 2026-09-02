from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, CHAT_SOURCE

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
    assert r.json()["detail"] == "Turing chat execution failed"

    plane = get_execution_plane()
    failed = _await(plane.run_store.list_by_status(RunStatus.FAILED, limit=10))
    assert len(failed) == 1
    node_runs = _await(plane.run_store.list_node_runs(failed[0].run_id))
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.FAILED
    attempts = _await(plane.run_store.list_attempts(node_runs[0].node_run_id))
    assert len(attempts) == 1


def test_provider_failure_detail_is_not_returned_to_the_caller(authed_client, monkeypatch):
    from ..state import get_state

    secret = "https://provider.invalid/v1 key=do-not-return"

    def fail_provider(*_args: Any, **_kwargs: Any) -> str:
        raise ValueError(secret)

    monkeypatch.setattr(get_state().provider, "complete", fail_provider, raising=True)

    response = authed_client.post("/v1/chat", json={"message": "hey"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Turing chat execution failed"
    assert secret not in response.text


def test_cancelled_chat_terminalizes_canonical_evidence():
    from ..execution import TuringExecutionPlane

    async def scenario() -> None:
        started = asyncio.Event()

        class BlockingSession:
            async def handle_message(self, _message: str) -> str:
                started.set()
                await asyncio.Event().wait()
                raise AssertionError("blocking chat should have been cancelled")

        plane = TuringExecutionPlane()
        task = asyncio.create_task(
            plane.run_chat(
                session=BlockingSession(),  # type: ignore[arg-type]
                user_id="user",
                session_id="session",
                message="hello",
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        cancelled = await plane.run_store.list_by_status(RunStatus.CANCELLED, limit=10)
        assert len(cancelled) == 1
        node_runs = await plane.run_store.list_node_runs(cancelled[0].run_id)
        assert len(node_runs) == 1
        assert node_runs[0].status is RunStatus.CANCELLED
        attempts = await plane.run_store.list_attempts(node_runs[0].node_run_id)
        assert len(attempts) == 1
        assert attempts[0].status is AttemptStatus.CANCELLED

    _await(scenario())


def test_turing_chat_admission_uses_chat_retention_and_bounded_window():
    from ..execution import TuringExecutionPlane

    class ReplySession:
        async def handle_message(self, message: str) -> str:
            return f"reply:{message}"

    async def scenario() -> None:
        plane = TuringExecutionPlane(max_retained=1)
        session = ReplySession()
        first = await plane.run_chat(
            session=session,  # type: ignore[arg-type]
            user_id="user",
            session_id="session",
            message="one",
        )
        second = await plane.run_chat(
            session=session,  # type: ignore[arg-type]
            user_id="user",
            session_id="session",
            message="two",
        )

        assert await plane.run_store.get_run(first.run_id) is None
        retained = await plane.run_store.get_run(second.run_id)
        assert retained is not None
        assert retained.provenance[ADMISSION_SOURCE] == CHAT_SOURCE
        assert retained.retention_expires_at is not None
        assert plane.retained == 1

    _await(scenario())


def test_turing_execution_plane_rejects_an_empty_retention_window():
    from ..execution import TuringExecutionPlane

    with pytest.raises(ValueError, match="max_retained must be >= 1"):
        TuringExecutionPlane(max_retained=0)


def test_retention_window_preserves_active_runs_and_drops_missing_entries():
    from maistro.graph import Graph, Node

    from ..execution import TuringExecutionPlane

    async def scenario() -> None:
        plane = TuringExecutionPlane(max_retained=1)
        workspace_id, project_id = await plane._scope_for("user")
        graph = Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name="active chat admission",
            nodes=[Node(node_id="active", node_type="test", name="active")],
        )
        active = await plane.run_store.create_run(
            graph,
            actor_principal_id="user",
            initial_status=RunStatus.QUEUED,
        )
        plane._retained_runs[active.run_id] = None

        await plane._track_admission("missing-run")

        assert list(plane._retained_runs) == [active.run_id]
        assert await plane.run_store.get_run(active.run_id) is not None

    _await(scenario())


def test_turing_cleanup_helpers_fail_closed_without_masking_the_caller(monkeypatch, caplog):
    from ..execution import TuringExecutionPlane

    async def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("cleanup store unavailable")

    async def scenario() -> None:
        plane = TuringExecutionPlane()

        await plane._cancel_incomplete_admission(None)
        await plane._cancel_incomplete_admission("missing-run")

        monkeypatch.setattr(plane.durable_store, "get", fail)
        await plane._clear_continuation("run")

        monkeypatch.setattr(plane.run_store, "get_run", fail)
        await plane._cancel_incomplete_admission("run")

        monkeypatch.setattr(plane.run_store, "list_node_runs", fail)
        await plane._cancel_execution("run")

    _await(scenario())

    assert "Turing continuation cleanup failed" in caplog.text
    assert "could not be compensated" in caplog.text
    assert "Turing cancellation cleanup failed" in caplog.text


def test_outer_cancellation_terminalizes_active_evidence_with_and_without_a_lease():
    from maistro.graph import Graph, Node

    from ..execution import TuringExecutionPlane

    async def scenario() -> None:
        plane = TuringExecutionPlane()
        workspace_id, project_id = await plane._scope_for("user")
        graph = Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name="active cancellation",
            nodes=[
                Node(node_id="leased", node_type="test", name="leased"),
                Node(node_id="unleased", node_type="test", name="unleased"),
            ],
        )
        run = await plane.run_store.create_run(
            graph,
            actor_principal_id="user",
            initial_status=RunStatus.QUEUED,
        )
        await plane.run_store.transition_run(run.run_id, RunStatus.RUNNING)

        attempts = []
        for node_id, lease_holder in (("leased", "worker"), ("unleased", None)):
            node_run = await plane.run_store.create_node_run(run.run_id, node_id=node_id)
            await plane.run_store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
            await plane.run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
            attempt = await plane.run_store.create_attempt(
                node_run.node_run_id,
                lease_holder=lease_holder,
            )
            token = (
                attempt.execution_lease.fencing_token
                if attempt.execution_lease is not None
                else None
            )
            attempt = await plane.run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.RUNNING,
                fencing_token=token,
            )
            attempts.append(attempt)

        await plane._cancel_execution(run.run_id)

        cancelled_run = await plane.run_store.get_run(run.run_id)
        assert cancelled_run is not None
        assert cancelled_run.status is RunStatus.CANCELLED
        for attempt in attempts:
            cancelled_attempt = await plane.run_store.get_attempt(attempt.attempt_id)
            assert cancelled_attempt is not None
            assert cancelled_attempt.status is AttemptStatus.CANCELLED
        for node_run in await plane.run_store.list_node_runs(run.run_id):
            assert node_run.status is RunStatus.CANCELLED

    _await(scenario())


def test_cancelled_partial_admission_is_compensated_before_dispatch(monkeypatch):
    from maistro.runs.chat_admission import ADMISSION_INCOMPLETE

    from ..execution import TuringExecutionPlane

    async def scenario() -> None:
        plane = TuringExecutionPlane()
        admitted = asyncio.Event()

        async def block_after_create(_run_id: str) -> None:
            admitted.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(plane, "_track_admission", block_after_create)
        task = asyncio.create_task(
            plane.run_chat(
                session=object(),  # type: ignore[arg-type]
                user_id="user",
                session_id="session",
                message="hello",
            )
        )
        await asyncio.wait_for(admitted.wait(), timeout=1)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        cancelled = await plane.run_store.list_by_status(RunStatus.CANCELLED, limit=10)
        assert len(cancelled) == 1
        assert cancelled[0].error == ADMISSION_INCOMPLETE

    _await(scenario())


def test_create_run_failure_does_not_make_chat_unavailable(authed_client, monkeypatch):
    from ..execution import get_execution_plane
    from ..state import get_state

    plane = get_execution_plane()
    provider_calls = 0

    def reply(*_args: Any, **_kwargs: Any) -> str:
        nonlocal provider_calls
        provider_calls += 1
        return "available without audit"

    async def fail_create(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("run store unavailable")

    monkeypatch.setattr(get_state().provider, "complete", reply, raising=True)
    monkeypatch.setattr(plane.run_store, "create_run", fail_create)

    response = authed_client.post("/v1/chat", json={"message": "hey"})

    assert response.status_code == 200
    assert response.json()["reply"] == "available without audit"
    assert response.json()["run_id"] is None
    assert provider_calls == 1


def test_unrecorded_reply_propagates_cancellation():
    from ..routes.chat import _unrecorded_reply

    class CancelledSession:
        async def handle_message(self, _message: str) -> str:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _await(_unrecorded_reply(CancelledSession(), "hello"))  # type: ignore[arg-type]


def test_unrecorded_reply_sanitizes_provider_failure():
    from fastapi import HTTPException

    from ..routes.chat import _unrecorded_reply

    secret = "https://provider.invalid token=do-not-return"

    class FailingSession:
        async def handle_message(self, _message: str) -> str:
            raise RuntimeError(secret)

    with pytest.raises(HTTPException) as caught:
        _await(_unrecorded_reply(FailingSession(), "hello"))  # type: ignore[arg-type]

    assert caught.value.status_code == 503
    assert caught.value.detail == "Turing chat execution failed"
    assert secret not in str(caught.value.detail)


def test_chat_sanitizes_a_completed_run_with_missing_reply(authed_client, monkeypatch):
    from ..routes import chat as chat_module

    record: Any = SimpleNamespace(
        run=SimpleNamespace(status=RunStatus.COMPLETED),
        run_id="run-without-reply",
        node_runs=[],
    )

    class ProjectionFailurePlane:
        async def run_chat(self, **_kwargs: Any) -> Any:
            return record

    monkeypatch.setattr(chat_module, "get_execution_plane", lambda: ProjectionFailurePlane())

    response = authed_client.post("/v1/chat", json={"message": "hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Turing chat execution failed"


def test_checkpoint_admission_failure_is_compensated_before_unrecorded_chat(
    authed_client, monkeypatch
):
    from maistro.runs.chat_admission import ADMISSION_INCOMPLETE

    from ..execution import get_execution_plane
    from ..state import get_state

    plane = get_execution_plane()
    provider_calls = 0

    def reply(*_args: Any, **_kwargs: Any) -> str:
        nonlocal provider_calls
        provider_calls += 1
        return "available after checkpoint failure"

    async def fail_checkpoint(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("continuation store unavailable")

    monkeypatch.setattr(get_state().provider, "complete", reply, raising=True)
    monkeypatch.setattr(plane.durable_store, "create", fail_checkpoint)

    response = authed_client.post("/v1/chat", json={"message": "hey"})

    assert response.status_code == 200
    assert response.json()["reply"] == "available after checkpoint failure"
    assert response.json()["run_id"] is None
    assert provider_calls == 1

    cancelled = _await(plane.run_store.list_by_status(RunStatus.CANCELLED, limit=10))
    assert len(cancelled) == 1
    assert cancelled[0].error == ADMISSION_INCOMPLETE


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
