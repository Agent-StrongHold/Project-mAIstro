"""Route-level coverage for routes/chat.py (session CRUD + complete/stream).

The streaming/non-streaming completion *logic* (tool-call accumulation,
SSE event shapes) is already covered end-to-end against the service layer
in test_chat_streaming.py. This file covers the HTTP route surface itself:
session list/create/get/delete, message append, and the two completion
endpoints through the M0 conversational-only route boundary.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from services import conversation_sessions, workspace_authority  # noqa: E402

# Model-reaching turns are admitted as canonical chat Runs (#1037).
pytestmark = pytest.mark.usefixtures("chat_run_spine")

# Model-reaching turns are admitted as canonical chat Runs (#1037).
pytestmark = pytest.mark.usefixtures("chat_run_spine")


def _clear(store) -> None:
    for key in list(store.keys()):
        store.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_chat_sessions():
    _clear(stores.chat_sessions)
    conversation_sessions.reset_for_tests()
    yield
    _clear(stores.chat_sessions)
    conversation_sessions.reset_for_tests()


def _workspace(owner: str = "user", name: str = "chat routes") -> str:
    view = asyncio.run(
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


def _create(client: Any, title: str = "x", *, workspace_id: str | None = None) -> str:
    ws = workspace_id or _workspace()
    r = client.post("/v1/chat/sessions", json={"title": title, "workspace_id": ws})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# GET /sessions
# --------------------------------------------------------------------------- #


def test_list_sessions_requires_workspace_id(authed_client: Any) -> None:
    r = authed_client.get("/v1/chat/sessions")
    assert r.status_code == 422


def test_list_sessions_empty_for_new_workspace(authed_client: Any) -> None:
    ws = _workspace()
    r = authed_client.get(f"/v1/chat/sessions?workspace_id={ws}")
    assert r.status_code == 200
    assert r.json() == []


def test_list_sessions_sorted_by_updated_at_desc(authed_client: Any) -> None:
    ws = _workspace()
    _create(authed_client, "first", workspace_id=ws)
    _create(authed_client, "second", workspace_id=ws)
    r = authed_client.get(f"/v1/chat/sessions?workspace_id={ws}")
    titles = [s["title"] for s in r.json()]
    # second was created after first, so it sorts before it (reverse=True)
    assert titles.index("second") < titles.index("first")


# --------------------------------------------------------------------------- #
# POST /sessions
# --------------------------------------------------------------------------- #


def test_create_session_requires_workspace_id(authed_client: Any) -> None:
    r = authed_client.post("/v1/chat/sessions", json={"title": "x"})
    assert r.status_code == 422


def test_create_session_default_title(authed_client: Any) -> None:
    ws = _workspace()
    r = authed_client.post("/v1/chat/sessions", json={"workspace_id": ws})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "New chat"
    assert body["messages"] == []
    assert body["workspace_id"] == ws
    assert body["id"] in conversation_sessions.session_meta_store


def test_create_session_custom_title(authed_client: Any) -> None:
    ws = _workspace()
    r = authed_client.post("/v1/chat/sessions", json={"title": "My chat", "workspace_id": ws})
    assert r.json()["title"] == "My chat"


def test_create_session_foreign_workspace_is_404(authed_client: Any) -> None:
    r = authed_client.post(
        "/v1/chat/sessions",
        json={"title": "nope", "workspace_id": "not-a-real-workspace"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "workspace not found"


# --------------------------------------------------------------------------- #
# GET /sessions/{id}
# --------------------------------------------------------------------------- #


def test_get_session_found(authed_client: Any) -> None:
    sid = _create(authed_client, "x")
    r = authed_client.get(f"/v1/chat/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid


def test_get_session_missing_404(authed_client: Any) -> None:
    r = authed_client.get("/v1/chat/sessions/does-not-exist")
    assert r.status_code == 404
    assert r.json()["detail"] == "session not found"


# --------------------------------------------------------------------------- #
# DELETE /sessions/{id}
# --------------------------------------------------------------------------- #


def test_delete_session_removes_it(authed_client: Any) -> None:
    sid = _create(authed_client, "x")
    r = authed_client.delete(f"/v1/chat/sessions/{sid}")
    assert r.status_code == 204
    assert sid not in conversation_sessions.session_meta_store


def test_delete_session_missing_is_noop(authed_client: Any) -> None:
    r = authed_client.delete("/v1/chat/sessions/never-existed")
    assert r.status_code == 204


# --------------------------------------------------------------------------- #
# POST /sessions/{id}/messages
# --------------------------------------------------------------------------- #


def test_append_message_to_existing_session(authed_client: Any) -> None:
    sid = _create(authed_client, "x")
    r = authed_client.post(
        f"/v1/chat/sessions/{sid}/messages", json={"role": "user", "content": "hi there"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "user"
    assert body["content"] == "hi there"
    got = authed_client.get(f"/v1/chat/sessions/{sid}").json()
    assert len(got["messages"]) == 1
    assert got["messages"][0]["content"] == "hi there"


def test_append_message_default_role_is_user(authed_client: Any) -> None:
    sid = _create(authed_client, "x")
    r = authed_client.post(f"/v1/chat/sessions/{sid}/messages", json={"content": "no role given"})
    assert r.json()["role"] == "user"


def test_append_message_missing_session_404(authed_client: Any) -> None:
    r = authed_client.post(
        "/v1/chat/sessions/missing/messages", json={"role": "user", "content": "hi"}
    )
    assert r.status_code == 404


def test_append_message_updates_session_updated_at(authed_client: Any) -> None:
    sid = _create(authed_client, "x")
    before = conversation_sessions.require_owned("user", sid).updated_at
    authed_client.post(f"/v1/chat/sessions/{sid}/messages", json={"role": "user", "content": "x"})
    after = conversation_sessions.require_owned("user", sid).updated_at
    assert after >= before


def test_append_message_system_role_accepted_without_session_store_persist(
    authed_client: Any,
) -> None:
    """SessionStore only keeps user/assistant; system is shape-parity only."""
    sid = _create(authed_client, "x")
    r = authed_client.post(
        f"/v1/chat/sessions/{sid}/messages",
        json={"role": "system", "content": "operator note"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "system"
    assert r.json()["content"] == "operator note"
    got = authed_client.get(f"/v1/chat/sessions/{sid}").json()
    assert got["messages"] == []


def test_history_as_messages_skips_unknown_roles() -> None:
    from routes.chat import _history_as_messages

    msgs = _history_as_messages(
        "sess-1",
        [
            {"role": "user", "content": "a"},
            {"role": "narrator", "content": "skip me"},
            {"role": "assistant", "content": "b"},
        ],
    )
    assert [(m.role, m.content) for m in msgs] == [("user", "a"), ("assistant", "b")]


# --------------------------------------------------------------------------- #
# POST /complete
# --------------------------------------------------------------------------- #


def test_complete_calls_conversational_llm_without_tools(authed_client: Any, monkeypatch) -> None:
    captured: list[Any] = []

    class FakeLLM:
        async def complete(self, req):
            captured.append(req)
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr("routes.chat.build_llm_port", lambda: FakeLLM())

    r = authed_client.post(
        "/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "hi"}], "model": "test-model"},
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "ok"
    req = captured[0]
    assert req.messages[0]["role"] == "system"
    assert "conversational-only" in req.messages[0]["content"]
    assert req.messages[1]["content"] == "hi"
    assert req.tools is None
    assert req.model == "test-model"

    r = authed_client.post(
        "/v1/chat/complete",
        json={
            "messages": [
                {"role": "system", "content": "caller context"},
                {"role": "user", "content": "hello"},
            ],
            "model": "test-model",
        },
    )
    assert r.status_code == 200
    caller_req = captured[1]
    assert [message["role"] for message in caller_req.messages] == ["system", "user"]
    assert caller_req.messages[0]["content"] == "caller context"
    assert caller_req.messages[1]["content"] == "hello"
    assert caller_req.tools is None


# --------------------------------------------------------------------------- #
# POST /stream
# --------------------------------------------------------------------------- #


def test_stream_emits_single_done_event_from_conversational_llm(
    authed_client: Any, monkeypatch
) -> None:
    class FakeLLM:
        async def complete(self, req):
            assert req.tools is None
            return {"choices": [{"message": {"role": "assistant", "content": "Hello"}}]}

    monkeypatch.setattr("routes.chat.build_llm_port", lambda: FakeLLM())

    with authed_client.stream(
        "POST",
        "/v1/chat/stream",
        json={"messages": [{"role": "user", "content": "hi"}], "model": "test-model"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert '"type": "done"' in body or '"type":"done"' in body
    assert "Hello" in body
    assert '"type": "delta"' not in body and '"type":"delta"' not in body


def test_stream_preserves_caller_provided_system_message(authed_client: Any, monkeypatch) -> None:
    captured: list[Any] = []

    class FakeLLM:
        async def complete(self, req):
            captured.append(req)
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr("routes.chat.build_llm_port", lambda: FakeLLM())

    with authed_client.stream(
        "POST",
        "/v1/chat/stream",
        json={
            "messages": [
                {"role": "system", "content": "caller context"},
                {"role": "user", "content": "hello"},
            ],
            "model": "test-model",
        },
    ) as r:
        assert r.status_code == 200
        "".join(r.iter_text())

    req = captured[0]
    assert [message["role"] for message in req.messages] == ["system", "user"]
    assert req.messages[0]["content"] == "caller context"


def test_stream_swallows_llm_exception_as_done_event(authed_client: Any, monkeypatch) -> None:
    class FailingLLM:
        async def complete(self, req):
            raise RuntimeError("boom")

    monkeypatch.setattr("routes.chat.build_llm_port", lambda: FailingLLM())

    with authed_client.stream(
        "POST",
        "/v1/chat/stream",
        json={"messages": [{"role": "user", "content": "hi"}], "model": "test-model"},
    ) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "Error: RuntimeError" in body
