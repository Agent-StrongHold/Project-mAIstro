"""routes/program.py -- the brief interview a Goal is committed from
(SPEC-091726-7c2a), hosted beside the onboarding interview. Scoped to a
workspace the caller is a member of, one interview per person per workspace,
and the draft endpoint is the gate: 409 with the missing fields until every
required one is known.
"""

from __future__ import annotations

import pytest
import stores

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture(autouse=True)
def _clear_state():
    for store in (stores.workspaces, stores.program_contexts, stores.brief_interviews):
        for key in list(store.keys()):
            store.pop(key, None)
    yield
    for store in (stores.workspaces, stores.program_contexts, stores.brief_interviews):
        for key in list(store.keys()):
            store.pop(key, None)


def _create_workspace(admin_client, persona_template_id: str = "content_creator") -> str:
    r = admin_client.post(
        "/v1/workspaces",
        json={"persona_template_id": persona_template_id, "name": "Rooted Craft Co"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_a_request_without_a_workspace_is_refused(admin_client) -> None:
    assert admin_client.get("/v1/program/brief").status_code == 404
    r = admin_client.post("/v1/program/brief/start", json={"opening": "a new video"})
    assert r.status_code == 404


@pytest.mark.ac("SPEC-091726-7c2a/AC-1")
def test_starting_opens_an_interview_and_the_draft_is_refused(admin_client) -> None:
    ws = _create_workspace(admin_client)
    assert admin_client.get(f"/v1/program/brief?workspace_id={ws}").json()["interview"] is None

    r = admin_client.post(
        f"/v1/program/brief/start?workspace_id={ws}",
        json={"opening": "Let's make a new video, let's start drafting a storyboard"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["summary"]["known"] == 0
    assert body["summary"]["needed"] == 5
    assert body["question"]["key"] == "subject"
    assert body["question"]["can_assume"] is False

    r = admin_client.post(f"/v1/program/brief/draft?workspace_id={ws}")
    assert r.status_code == 409
    assert r.json()["detail"]["missing"] == ["subject", "outcome", "channel", "source", "deadline"]


@pytest.mark.ac("SPEC-091726-7c2a/AC-2")
@pytest.mark.ac("SPEC-091726-7c2a/AC-8")
def test_answers_move_the_interview_and_the_draft_names_what_was_assumed(admin_client) -> None:
    ws = _create_workspace(admin_client)
    admin_client.post(
        f"/v1/program/brief/start?workspace_id={ws}",
        json={"opening": "New reel about the grouting haze"},
    )
    asked: list[str] = []
    events: list[str] = []
    for text in ("the grouting haze fix", "teach it", "the assembled cut", "you decide"):
        before = admin_client.get(f"/v1/program/brief?workspace_id={ws}").json()
        asked.append(before["question"]["key"])
        r = admin_client.post(f"/v1/program/brief/answer?workspace_id={ws}", json={"answer": text})
        assert r.status_code == 200
        events.append(r.json()["event"])

    # channel came from the opening turn, so it was never asked
    assert asked == ["subject", "outcome", "source", "deadline"]
    assert events == ["answered", "answered", "answered", "assumed"]

    r = admin_client.post(f"/v1/program/brief/draft?workspace_id={ws}")
    assert r.status_code == 200
    draft = r.json()["draft"]
    assert draft["fields"]["channel"] == "a 30-second vertical reel"
    assert draft["sources"]["channel"] == "user"
    assert draft["sources"]["deadline"] == "assumed"
    assert draft["assumed"] == ["deadline", "voice", "claims", "mode"]
    assert r.json()["written"] == [], "no Goal or CreativeBrief store exists to write yet"


@pytest.mark.ac("SPEC-091726-7c2a/AC-7")
def test_never_mind_drops_and_delete_forgets(admin_client) -> None:
    ws = _create_workspace(admin_client)
    admin_client.post(f"/v1/program/brief/start?workspace_id={ws}", json={"opening": "a video"})
    r = admin_client.post(
        f"/v1/program/brief/answer?workspace_id={ws}", json={"answer": "never mind"}
    )
    assert r.json()["event"] == "dropped"
    assert admin_client.post(f"/v1/program/brief/draft?workspace_id={ws}").status_code == 409

    assert admin_client.delete(f"/v1/program/brief?workspace_id={ws}").json()["dropped"] is True
    assert admin_client.get(f"/v1/program/brief?workspace_id={ws}").json()["interview"] is None
    assert (
        admin_client.post(
            f"/v1/program/brief/answer?workspace_id={ws}", json={"answer": "x"}
        ).status_code
        == 404
    )


def test_two_workspaces_hold_independent_interviews(admin_client) -> None:
    ws_a = _create_workspace(admin_client)
    ws_b = _create_workspace(admin_client, "pm_fleet")
    admin_client.post(f"/v1/program/brief/start?workspace_id={ws_a}", json={"opening": "a reel"})
    assert admin_client.get(f"/v1/program/brief?workspace_id={ws_b}").json()["interview"] is None
    assert (
        admin_client.get(f"/v1/program/brief?workspace_id={ws_a}").json()["summary"]["known"] == 1
    )


def test_an_unknown_script_is_refused(admin_client) -> None:
    ws = _create_workspace(admin_client)
    r = admin_client.post(
        f"/v1/program/brief/start?workspace_id={ws}",
        json={"opening": "a poster", "script": "poster_brief"},
    )
    assert r.status_code == 404
