"""#1037: conversation-only Hive chat and voice turns run as canonical chat Runs.

Driven through the shipped routes on a real embedded Container (in-memory
stores) bound where the bridge binds it. The model is faked only at its HTTP
boundary: `build_llm_port` builds the real `HttpOpenAIProtocolLLM`, and the
socket underneath it is an `httpx.MockTransport`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from services import chat_runs, default_workspace, workspace_agent, workspace_authority

from maistro.container import Container, create_container
from maistro.http import override_transport
from maistro.runs.chat_admission import ChatRunAdmitter
from maistro.runs.chat_execution import ChatAttemptExecutor, ChatDispatchUnrecorded
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import RunIntegrityError
from maistro.types import AgentConfig

USER = "user"


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch) -> Iterator[Container]:
    from services.engine import get_engine

    built = asyncio.run(
        create_container(AgentConfig(router_api_key="test-key", database_url="memory://"))
    )
    monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=built))
    chat_runs.reset_for_tests()
    default_workspace.reset_for_tests()
    yield built
    chat_runs.reset_for_tests()
    default_workspace.reset_for_tests()


class _Gateway:
    """The model gateway's socket: records every request, answers or fails."""

    def __init__(self, *, content: str = "hello", status: int = 200) -> None:
        self.requests: list[dict[str, Any]] = []
        self._content = content
        self._status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content or b"{}"))
        if self._status != 200:
            return httpx.Response(self._status, json={"error": "upstream"})
        if request.url.path.endswith("/responses"):
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": self._content}],
                        }
                    ]
                },
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": self._content}}]}
        )


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Gateway]:
    monkeypatch.setenv("LITELLM_API_BASE", "https://gateway.invalid")
    monkeypatch.setenv("LITELLM_PROXY_KEY", "k")
    fake = _Gateway()
    with override_transport(httpx.MockTransport(fake)):
        yield fake


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _workspace(owner: str = USER, name: str = "Ops") -> str:
    view = _run(
        workspace_authority.create_workspace(
            creator_user_id=owner,
            name=name,
            persona_template_id="personal",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )
    )
    return view.id


def _evidence(container: Container, run_id: str) -> tuple[Any, list[Any], list[Any]]:
    async def _read() -> tuple[Any, list[Any], list[Any]]:
        run = await container.run_store.get_run(run_id)
        node_runs = await container.run_store.list_node_runs(run_id)
        attempts = [
            a for nr in node_runs for a in await container.run_store.list_attempts(nr.node_run_id)
        ]
        return run, node_runs, attempts

    return _run(_read())


def _runs_in(container: Container, workspace_id: str) -> list[Any]:
    async def _read() -> list[Any]:
        return [
            run
            for status in RunStatus
            for run in await container.run_store.list_by_status(status, workspace_id=workspace_id)
        ]

    return _run(_read())


def _complete(client: Any, **extra: Any) -> Any:
    return client.post(
        "/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "hi"}], "model": "m", **extra},
    )


def _stream(client: Any, **extra: Any) -> list[dict[str, Any]]:
    with client.stream(
        "POST",
        "/v1/chat/stream",
        json={"messages": [{"role": "user", "content": "hi"}], "model": "m", **extra},
    ) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    return [
        json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")
    ]


@pytest.mark.contract("behavioral")
def test_repeated_complete_turns_share_the_workspace_agent_under_distinct_runs(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    ws = _workspace()

    first = _complete(authed_client, workspace_id=ws)
    second = _complete(authed_client, workspace_id=ws)

    assert first.status_code == second.status_code == 200
    assert first.json()["choices"][0]["message"]["content"] == "hello"
    run_ids = [first.json()["run_id"], second.json()["run_id"]]
    assert len(set(run_ids)) == 2
    agent_id = _run(workspace_agent.resolve_workspace_agent(ws)).id
    assert agent_id == f"workspace-agent:{ws}"
    for run_id in run_ids:
        run, node_runs, attempts = _evidence(container, run_id)
        assert run.status is RunStatus.COMPLETED
        assert run.workspace_id == ws
        assert run.actor_principal_id == USER
        assert run.result["answer"] == "hello"
        assert len(node_runs) == 1
        assert len(attempts) == 1
        assert attempts[0].status is AttemptStatus.COMPLETED
        assert attempts[0].result["agent"] == agent_id
    assert first.json()["agent"] == agent_id


@pytest.mark.contract("behavioral")
def test_no_tool_is_offered_or_called_inside_the_run(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    tool = {"type": "function", "function": {"name": "shell", "parameters": {}}}

    r = _complete(authed_client, tools=[tool], tools_scope="anything")

    assert r.status_code == 200
    assert gateway.requests
    assert all("tools" not in sent for sent in gateway.requests)
    _run_obj, node_runs, attempts = _evidence(container, r.json()["run_id"])
    assert len(node_runs) == 1 and len(attempts) == 1


@pytest.mark.contract("behavioral")
def test_turn_without_workspace_lands_in_the_callers_default_workspace(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    r = _complete(authed_client)

    assert r.status_code == 200
    default = _run(default_workspace.resolve_default_workspace(USER))
    run, _node_runs, attempts = _evidence(container, r.json()["run_id"])
    assert run.workspace_id == default.id
    assert attempts[0].result["agent"] == f"workspace-agent:{default.id}"


@pytest.mark.contract("behavioral")
def test_named_workspace_the_caller_is_not_a_member_of_files_nothing_there(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    foreign = _workspace(owner="someone-else")

    r = _complete(authed_client, workspace_id=foreign)

    assert r.status_code == 200
    assert _runs_in(container, foreign) == []
    default = _run(default_workspace.resolve_default_workspace(USER))
    run, _node_runs, attempts = _evidence(container, r.json()["run_id"])
    assert run.workspace_id == default.id
    assert attempts[0].result["agent"] == f"workspace-agent:{default.id}"


@pytest.mark.contract("behavioral")
def test_session_id_is_provenance_not_a_second_run_identity(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    ws = _workspace()
    sid = authed_client.post("/v1/chat/sessions", json={"title": "t"}).json()["id"]

    first = _complete(authed_client, workspace_id=ws, session_id=sid)
    second = _complete(authed_client, workspace_id=ws, session_id=sid)

    run_ids = {first.json()["run_id"], second.json()["run_id"]}
    assert len(run_ids) == 2
    assert sid not in run_ids
    for run_id in run_ids:
        run, _node_runs, _attempts = _evidence(container, run_id)
        assert run.provenance["session_id"] == sid


@pytest.mark.contract("behavioral")
def test_a_session_id_the_caller_does_not_own_is_not_recorded(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    from datetime import UTC, datetime

    from models.schemas import ChatSession
    from services.owned_records import Owner, owned_chat_sessions

    now = datetime.now(UTC)
    foreign = "someone-elses-session"
    owned_chat_sessions(Owner(id="someone-else")).create(
        foreign, ChatSession(id=foreign, title="t", messages=[], created_at=now, updated_at=now)
    )

    r = _complete(authed_client, session_id=foreign)

    assert r.status_code == 200
    run, _node_runs, _attempts = _evidence(container, r.json()["run_id"])
    assert "session_id" not in run.provenance
    owned_chat_sessions(Owner(id="someone-else")).discard(foreign)


@pytest.mark.contract("behavioral")
def test_stream_turn_returns_its_run_id_and_completes_the_run(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    ws = _workspace()

    events = _stream(authed_client, workspace_id=ws)

    (done,) = [e for e in events if e.get("type") == "done"]
    assert done["content"] == "hello"
    run, node_runs, attempts = _evidence(container, done["run_id"])
    assert run.status is RunStatus.COMPLETED
    assert len(node_runs) == 1 and len(attempts) == 1
    assert attempts[0].result["agent"] == f"workspace-agent:{ws}"


@pytest.mark.contract("behavioral")
def test_model_failure_on_stream_fails_the_run_and_reports_an_error(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    gateway._status = 500

    events = _stream(authed_client)

    (done,) = [e for e in events if e.get("type") == "done"]
    assert done["content"].startswith("Error:")
    run, _node_runs, attempts = _evidence(container, done["run_id"])
    assert run.status is RunStatus.FAILED
    assert run.result is None
    assert [a.status for a in attempts] == [AttemptStatus.FAILED]


@pytest.mark.contract("behavioral")
def test_model_failure_on_complete_fails_the_run(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    ws = _workspace()
    gateway._status = 500

    with pytest.raises(httpx.HTTPStatusError):
        _complete(authed_client, workspace_id=ws)

    (run,) = _runs_in(container, ws)
    assert run.status is RunStatus.FAILED
    _run_obj, _node_runs, attempts = _evidence(container, run.run_id)
    assert [a.status for a in attempts] == [AttemptStatus.FAILED]


@pytest.mark.contract("behavioral")
@pytest.mark.parametrize("route", ["/v1/chat/complete", "/v1/chat/stream", "/v1/voice/intent"])
def test_admission_failure_refuses_with_retryable_503_before_the_model(
    authed_client: Any,
    container: Container,
    gateway: _Gateway,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    async def _refuse(self: ChatRunAdmitter, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("run store down")

    monkeypatch.setattr(ChatRunAdmitter, "admit", _refuse)
    body: dict[str, Any] = (
        {"text": "hi"}
        if route.endswith("intent")
        else {"messages": [{"role": "user", "content": "hi"}], "model": "m"}
    )

    r = authed_client.post(route, json=body)

    assert r.status_code == 503
    assert r.headers["Retry-After"]
    assert gateway.requests == []


@pytest.mark.contract("behavioral")
def test_no_run_store_refuses_with_retryable_503(
    authed_client: Any, gateway: _Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapters.maistro_core import StubAgentPort
    from services.engine import get_engine

    monkeypatch.setattr(get_engine(), "_agent_port", StubAgentPort())

    r = _complete(authed_client)

    assert r.status_code == 503
    assert r.headers["Retry-After"]
    assert gateway.requests == []


@pytest.mark.contract("behavioral")
def test_voice_intent_turn_runs_under_the_default_workspace_agent(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    r = authed_client.post("/v1/voice/intent", json={"text": "hi", "room": "kitchen"})

    assert r.status_code == 200
    assert r.json()["reply"] == "hello"
    run, node_runs, attempts = _evidence(container, r.json()["run_id"])
    default = _run(default_workspace.resolve_default_workspace(USER))
    assert run.status is RunStatus.COMPLETED
    assert run.workspace_id == default.id
    assert len(node_runs) == 1 and len(attempts) == 1
    assert attempts[0].result["agent"] == f"workspace-agent:{default.id}"
    assert all("tools" not in sent for sent in gateway.requests)


@pytest.mark.contract("behavioral")
def test_an_answer_the_spine_could_not_record_is_returned_once_with_the_run_left_open(
    authed_client: Any, container: Container, gateway: _Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1108: never a second model call, never a success-shaped terminal Run."""
    real_execute = ChatAttemptExecutor.execute

    async def _answered_then_unrecorded(
        self: ChatAttemptExecutor, run_id: str, messages: Any, dispatch: Any
    ) -> dict[str, Any]:
        response = await dispatch()
        raise ChatDispatchUnrecorded(run_id, response=response)

    monkeypatch.setattr(ChatAttemptExecutor, "execute", _answered_then_unrecorded)

    r = _complete(authed_client)

    monkeypatch.setattr(ChatAttemptExecutor, "execute", real_execute)
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hello"
    assert len(gateway.requests) == 1
    run, _node_runs, _attempts = _evidence(container, r.json()["run_id"])
    assert run.status is RunStatus.RUNNING


def _principal() -> Any:
    return SimpleNamespace(state=SimpleNamespace(user={"id": USER}))


@pytest.mark.contract("behavioral")
def test_a_cancelled_model_call_cancels_the_run(container: Container) -> None:
    async def _cancelled() -> dict[str, Any]:
        raise asyncio.CancelledError

    async def _turn() -> str:
        messages = [{"role": "user", "content": "hi"}]
        turn = await chat_runs.admit_turn(_principal(), messages)  # type: ignore[arg-type]
        with pytest.raises(asyncio.CancelledError):
            await chat_runs.execute_turn(turn, messages, _cancelled)
        return turn.run.run_id

    run, _node_runs, _attempts = _evidence(container, _run(_turn()))
    assert run.status is RunStatus.CANCELLED


@pytest.mark.contract("behavioral")
def test_a_cancellation_mid_admission_leaves_no_queued_run(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_transition = container.run_store.transition_run

    async def _cancel_at_running(run_id: str, status: RunStatus, **kwargs: Any) -> Any:
        if status is RunStatus.RUNNING:
            raise asyncio.CancelledError
        return await real_transition(run_id, status, **kwargs)

    monkeypatch.setattr(container.run_store, "transition_run", _cancel_at_running)

    async def _turn() -> None:
        with pytest.raises(asyncio.CancelledError):
            await chat_runs.admit_turn(_principal(), [{"role": "user", "content": "hi"}])  # type: ignore[arg-type]

    _run(_turn())
    monkeypatch.setattr(container.run_store, "transition_run", real_transition)
    default = _run(default_workspace.resolve_default_workspace(USER))
    (run,) = _runs_in(container, default.id)
    assert run.status is RunStatus.CANCELLED


@pytest.mark.contract("behavioral")
def test_a_stream_whose_body_never_runs_cancels_its_run(
    container: Container, gateway: _Gateway
) -> None:
    from models.schemas import ChatCompletionRequest
    from routes import chat

    async def _disconnected_before_first_byte() -> str:
        req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="m")
        response = await chat.stream_complete(req, _principal())  # type: ignore[arg-type]

        async def _receive() -> dict[str, Any]:
            return {"type": "http.disconnect"}

        async def _send(message: dict[str, Any]) -> None:
            raise OSError("client gone")

        scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
        with contextlib.suppress(Exception):
            await response(scope, _receive, _send)
        return response.body_iterator  # type: ignore[no-any-return]

    _run(_disconnected_before_first_byte())
    default = _run(default_workspace.resolve_default_workspace(USER))
    (run,) = _runs_in(container, default.id)
    assert run.status is RunStatus.CANCELLED
    assert gateway.requests == []


@pytest.mark.contract("behavioral")
def test_a_spine_refusal_before_the_model_is_a_retryable_503(
    authed_client: Any, container: Container, gateway: _Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _refused(self: ChatAttemptExecutor, run_id: str, *args: Any) -> Any:
        raise RunIntegrityError(f"Run {run_id!r} does not exist")

    monkeypatch.setattr(ChatAttemptExecutor, "execute", _refused)
    ws = _workspace()

    r = _complete(authed_client, workspace_id=ws)

    assert r.status_code == 503
    assert r.headers["Retry-After"]
    assert gateway.requests == []
    (run,) = _runs_in(container, ws)
    assert run.status is RunStatus.CANCELLED


@pytest.mark.contract("behavioral")
def test_a_member_workspace_without_a_view_falls_back_to_the_default(
    authed_client: Any, container: Container, gateway: _Gateway
) -> None:
    ws = _workspace()
    workspace_authority.presentation_store().pop(ws)

    r = _complete(authed_client, workspace_id=ws)

    assert r.status_code == 200
    default = _run(default_workspace.resolve_default_workspace(USER))
    run, _node_runs, _attempts = _evidence(container, r.json()["run_id"])
    assert run.workspace_id == default.id
    assert _runs_in(container, ws) == []
