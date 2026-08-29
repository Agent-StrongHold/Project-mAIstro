"""Route-level coverage for routes/chat.py (session CRUD + complete/stream).

The streaming/non-streaming completion *logic* (tool-call accumulation,
SSE event shapes) is already covered end-to-end against the service layer
in test_chat_streaming.py. This file covers the HTTP route surface itself:
session list/create/get/delete, message append, and the two completion
endpoints through the M0 conversational-only route boundary.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402


def _clear(store) -> None:
    for key in list(store.keys()):
        store.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_chat_sessions():
    _clear(stores.chat_sessions)
    yield
    _clear(stores.chat_sessions)


# --------------------------------------------------------------------------- #
# GET /sessions
# --------------------------------------------------------------------------- #


def test_list_sessions_seeds_when_empty(authed_client: Any) -> None:
    r = authed_client.get("/v1/chat/sessions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    assert body[0]["title"] == "Welcome"
    assert "message_count" in body[0]


def test_list_sessions_sorted_by_updated_at_desc(authed_client: Any) -> None:
    authed_client.post("/v1/chat/sessions", json={"title": "first"})
    authed_client.post("/v1/chat/sessions", json={"title": "second"})
    r = authed_client.get("/v1/chat/sessions")
    titles = [s["title"] for s in r.json()]
    # second was created after first, so it sorts before it (reverse=True)
    assert titles.index("second") < titles.index("first")


# --------------------------------------------------------------------------- #
# POST /sessions
# --------------------------------------------------------------------------- #


def test_create_session_default_title(authed_client: Any) -> None:
    r = authed_client.post("/v1/chat/sessions", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "New chat"
    assert body["messages"] == []
    assert body["id"] in stores.chat_sessions


def test_create_session_custom_title(authed_client: Any) -> None:
    r = authed_client.post("/v1/chat/sessions", json={"title": "My chat"})
    assert r.json()["title"] == "My chat"


# --------------------------------------------------------------------------- #
# GET /sessions/{id}
# --------------------------------------------------------------------------- #


def test_get_session_found(authed_client: Any) -> None:
    sid = authed_client.post("/v1/chat/sessions", json={"title": "x"}).json()["id"]
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
    sid = authed_client.post("/v1/chat/sessions", json={"title": "x"}).json()["id"]
    r = authed_client.delete(f"/v1/chat/sessions/{sid}")
    assert r.status_code == 204
    assert sid not in stores.chat_sessions


def test_delete_session_missing_is_noop(authed_client: Any) -> None:
    r = authed_client.delete("/v1/chat/sessions/never-existed")
    assert r.status_code == 204


# --------------------------------------------------------------------------- #
# POST /sessions/{id}/messages
# --------------------------------------------------------------------------- #


def test_append_message_to_existing_session(authed_client: Any) -> None:
    sid = authed_client.post("/v1/chat/sessions", json={"title": "x"}).json()["id"]
    r = authed_client.post(
        f"/v1/chat/sessions/{sid}/messages", json={"role": "user", "content": "hi there"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "user"
    assert body["content"] == "hi there"
    assert len(stores.chat_sessions[sid].messages) == 1


def test_append_message_default_role_is_user(authed_client: Any) -> None:
    sid = authed_client.post("/v1/chat/sessions", json={"title": "x"}).json()["id"]
    r = authed_client.post(f"/v1/chat/sessions/{sid}/messages", json={"content": "no role given"})
    assert r.json()["role"] == "user"


def test_append_message_missing_session_404(authed_client: Any) -> None:
    r = authed_client.post(
        "/v1/chat/sessions/missing/messages", json={"role": "user", "content": "hi"}
    )
    assert r.status_code == 404


def test_append_message_updates_session_updated_at(authed_client: Any) -> None:
    sid = authed_client.post("/v1/chat/sessions", json={"title": "x"}).json()["id"]
    before = stores.chat_sessions[sid].updated_at
    authed_client.post(f"/v1/chat/sessions/{sid}/messages", json={"role": "user", "content": "x"})
    after = stores.chat_sessions[sid].updated_at
    assert after >= before


# --------------------------------------------------------------------------- #
# POST /complete
# --------------------------------------------------------------------------- #


def test_complete_calls_conversational_llm_without_tools(authed_client: Any, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeLLM:
        async def complete(self, req):
            captured["request"] = req
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr("routes.chat.build_llm_port", lambda: FakeLLM())

    r = authed_client.post(
        "/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "hi"}], "model": "test-model"},
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "ok"
    req = captured["request"]
    assert req.messages[0]["content"] == "hi"
    assert req.tools is None
    assert req.model == "test-model"


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
