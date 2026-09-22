"""The brief interview runs as chat turns (SPEC-091726-7c2a, #53).

The admin account is blocked from chat (break-glass only), so the workspace
is created by the admin, shared with the regular user, and every chat turn is
the regular user's.

A turn in a workspace that asks for work is answered by the interview, not
the model; while an interview is open every turn there is an answer to it;
"never mind" hands the next turn back to the model; "commit it" produces the
draft and says nothing else was written. A turn with no workspace, or one
that asks a question, still reaches the model exactly as before.
"""

from __future__ import annotations

import json
from typing import Any

import hive_conductor.stores as stores
import pytest

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture(autouse=True)
def _clear_state():
    for store in (stores.workspaces, stores.brief_interviews):
        for key in list(store.keys()):
            store.pop(key, None)
    yield
    for store in (stores.workspaces, stores.brief_interviews):
        for key in list(store.keys()):
            store.pop(key, None)


class _CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, req):
        self.calls += 1
        return {"choices": [{"message": {"role": "assistant", "content": "model answer"}}]}


@pytest.fixture
def llm(monkeypatch) -> _CountingLLM:
    fake = _CountingLLM()
    monkeypatch.setattr("hive_conductor.routes.chat.build_llm_port", lambda: fake)
    return fake


def _workspace(admin_client, *, share_with_user: bool = True) -> str:
    r = admin_client.post(
        "/v1/workspaces",
        json={"persona_template_id": "content_creator", "name": "Rooted Craft Co"},
    )
    assert r.status_code == 201
    ws = r.json()["id"]
    if share_with_user:
        r = admin_client.post(
            f"/v1/workspaces/{ws}/members", json={"user_id": "user", "role": "editor"}
        )
        assert r.status_code == 200
    return ws


def _stream(client, text: str, workspace_id: str | None = None) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"messages": [{"role": "user", "content": text}], "model": "m"}
    if workspace_id:
        body["workspace_id"] = workspace_id
    with client.stream("POST", "/v1/chat/stream", json=body) as r:
        assert r.status_code == 200
        raw = "".join(r.iter_text())
    return [
        json.loads(frame.split("data:", 1)[1])
        for frame in raw.split("\n\n")
        if frame.strip().startswith("data:")
    ]


def test_a_turn_without_a_workspace_reaches_the_model_as_before(authed_client, llm) -> None:
    events = _stream(authed_client, "Let's make a new video")
    assert [e["type"] for e in events] == ["done"]
    assert events[0]["content"] == "model answer"
    assert llm.calls == 1


def test_a_question_in_a_workspace_reaches_the_model(admin_client, authed_client, llm) -> None:
    ws = _workspace(admin_client)
    events = _stream(authed_client, "What did you do overnight?", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1


@pytest.mark.ac("SPEC-091726-7c2a/AC-1")
def test_a_work_request_in_a_workspace_opens_the_interview_instead_of_the_model(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client)
    events = _stream(authed_client, "Let's make a new video, let's start drafting a storyboard", ws)

    assert [e["type"] for e in events] == ["brief", "done"]
    brief, done = events
    assert brief["event"] == "started"
    assert brief["summary"]["known"] == 0
    assert brief["question"]["key"] == "subject"
    assert "becomes a Goal" in done["content"]
    assert done["content"].endswith(brief["question"]["question"])
    assert llm.calls == 0, "the model is not asked while the interview owns the turn"


@pytest.mark.ac("SPEC-091726-7c2a/AC-2")
@pytest.mark.ac("SPEC-091726-7c2a/AC-8")
def test_answers_advance_the_interview_and_commit_produces_the_draft(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "New reel about the grouting haze", ws)

    seen: list[tuple[str, str | None]] = []
    for text in ("the grouting haze fix", "teach it", "the assembled cut", "you decide"):
        brief, done = _stream(authed_client, text, ws)
        seen.append((brief["event"], brief["question"] and brief["question"]["key"]))
        assert done["content"]
    assert seen == [
        ("answered", "outcome"),
        ("answered", "source"),
        ("answered", "deadline"),
        ("assumed", None),
    ]
    brief, done = _stream(authed_client, "keep the intro under three seconds", ws)
    assert brief["event"] == "noted", "once ready, a non-answer is a note, not a Goal change"
    assert "Here's what I'd commit" in done["content"]

    brief, done = _stream(authed_client, "commit it", ws)
    assert brief["event"] == "drafted"
    assert brief["written"] == []
    assert brief["draft"]["fields"]["channel"] == "a 30-second vertical reel"
    assert brief["draft"]["assumed"] == ["deadline", "voice", "claims", "mode"]
    assert "#458 and #774" in done["content"]
    assert brief["interview"] is None, "the interview is over once its draft exists"
    assert llm.calls == 0

    # And the next turn is the model's again.
    events = _stream(authed_client, "thanks", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1


@pytest.mark.ac("SPEC-091726-7c2a/AC-7")
def test_cancel_drops_and_hands_the_next_turn_to_the_model(
    admin_client, authed_client, llm
) -> None:
    """The Warden input boundary runs before the interview, as before every
    chat turn; "never mind" trips its injection patterns and is refused
    before the interview sees it, so the chat's drop word is "cancel"."""
    ws = _workspace(admin_client)
    _stream(authed_client, "start a storyboard for a new reel", ws)
    brief, done = _stream(authed_client, "cancel", ws)
    assert brief["event"] == "dropped"
    assert brief["interview"] is None
    assert "Nothing was committed" in done["content"]
    assert llm.calls == 0

    events = _stream(authed_client, "so what's on for saturday?", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1


@pytest.mark.ac("SPEC-091726-7c2a/AC-5")
def test_an_answer_for_another_field_is_routed_and_the_question_is_repeated(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "make a video", ws)
    _stream(authed_client, "the grouting haze", ws)
    _stream(authed_client, "teach it", ws)
    brief, done = _stream(authed_client, "after the market", ws)
    assert brief["event"] == "routed"
    assert brief["question"]["key"] == "channel"
    assert "put it there" in done["content"]
    assert done["content"].endswith(brief["question"]["question"])


def test_the_non_streaming_route_carries_the_same_brief(admin_client, authed_client, llm) -> None:
    ws = _workspace(admin_client)
    r = authed_client.post(
        "/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "let's draft a new reel"}],
            "model": "m",
            "workspace_id": ws,
        },
    )
    assert r.status_code == 200
    assert r.json()["brief"]["event"] == "started"
    assert "becomes a Goal" in r.json()["choices"][0]["message"]["content"]
    assert llm.calls == 0


def test_a_workspace_the_caller_is_not_a_member_of_is_the_models_turn(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client, share_with_user=False)
    events = _stream(authed_client, "let's make a new video", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1


@pytest.mark.ac("SPEC-091726-7c2a/AC-6")
def test_you_decide_is_refused_where_nothing_is_defensible(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "make a video", ws)
    brief, done = _stream(authed_client, "you decide", ws)
    assert brief["event"] == "cannot_assume"
    assert brief["question"]["key"] == "subject", "the subject stays open"
    assert "can't assume" in done["content"]
    assert not done["content"].endswith(brief["question"]["question"]), (
        "the refusal stands alone; the question is not repeated after it"
    )
    assert llm.calls == 0


def test_once_ready_a_vague_change_asks_which_field(admin_client, authed_client, llm) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "New reel about the grouting haze", ws)
    for text in ("the grouting haze fix", "teach it", "the assembled cut", "you decide"):
        _stream(authed_client, text, ws)
    brief, done = _stream(authed_client, "something's wrong", ws)
    assert brief["event"] == "noted"
    assert done["content"].startswith("Which one?")

    brief, done = _stream(authed_client, "change channel to youtube", ws)
    assert brief["event"] == "changed"
    assert "Channel:" in done["content"]
    assert llm.calls == 0


def test_an_interview_dropped_through_the_program_api_hands_chat_to_the_model(
    admin_client, authed_client, llm
) -> None:
    """The program routes leave a dropped interview in the store; the chat
    forgets it on the next turn and lets the model answer."""
    ws = _workspace(admin_client)
    r = authed_client.post(
        f"/v1/program/brief/start?workspace_id={ws}", json={"opening": "a video"}
    )
    assert r.status_code == 201
    r = authed_client.post(
        f"/v1/program/brief/answer?workspace_id={ws}", json={"answer": "never mind"}
    )
    assert r.json()["event"] == "dropped"

    events = _stream(authed_client, "what's on for saturday?", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1
    assert authed_client.get(f"/v1/program/brief?workspace_id={ws}").json()["interview"] is None


def test_a_blank_turn_in_a_workspace_is_the_models(admin_client, authed_client, llm) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "make a video", ws)
    events = _stream(authed_client, "   ", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1
