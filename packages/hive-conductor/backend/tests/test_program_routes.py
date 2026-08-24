"""routes/program.py -- Persona/Workspace system: the onboarding interview
(GET /context, POST /interview/answer) resolves an optional workspace_id to
that workspace's own ProgramContext + persona-specific interview script,
instead of always using the single global "default"/pm_fleet scope.
"""

from __future__ import annotations

import pytest
import stores


@pytest.fixture(autouse=True)
def _clear_state():
    for key in list(stores.workspaces.keys()):
        stores.workspaces.pop(key, None)
    for key in list(stores.program_contexts.keys()):
        stores.program_contexts.pop(key, None)
    yield
    for key in list(stores.workspaces.keys()):
        stores.workspaces.pop(key, None)
    for key in list(stores.program_contexts.keys()):
        stores.program_contexts.pop(key, None)


def _create_workspace(admin_client, persona_template_id: str) -> str:
    r = admin_client.post(
        "/v1/workspaces",
        json={"persona_template_id": persona_template_id, "name": "Test WS"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_omitted_workspace_id_is_refused(admin_client) -> None:
    """The default scope used to answer here, gated on the global POC flag.

    That meant the deployment's `HIVE_POC_MODE` decided whether a caller could
    read a program context at all, and the one they got belonged to no
    workspace. Since #129 the program hyperagent runs within a workspace and
    a request that names none is refused."""
    r = admin_client.get("/v1/program/context")
    assert r.status_code == 404


def test_workspace_scoped_interview_uses_the_personas_own_script(admin_client) -> None:
    ws_id = _create_workspace(admin_client, "content_creator")
    r = admin_client.get(f"/v1/program/context?workspace_id={ws_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["context"]["project_id"] == ws_id
    # content_creator has no dedicated interview script -- falls back to the
    # generic 4-question one, distinct from pm_fleet's 5.
    assert body["interview"]["total_steps"] == 4


def test_pm_fleet_workspace_gets_the_pm_fleet_script(admin_client) -> None:
    ws_id = _create_workspace(admin_client, "pm_fleet")
    r = admin_client.get(f"/v1/program/context?workspace_id={ws_id}")
    assert r.status_code == 200
    assert r.json()["interview"]["total_steps"] == 5


def test_unknown_workspace_id_is_refused(admin_client) -> None:
    r = admin_client.get("/v1/program/context?workspace_id=does-not-exist")
    assert r.status_code == 404


def test_workspace_id_for_a_workspace_the_caller_is_not_a_member_of_is_refused(
    admin_client, authed_client
) -> None:
    """Indistinguishable from an unknown workspace, so a caller cannot probe
    which workspace ids are real."""
    ws_id = _create_workspace(admin_client, "content_creator")
    r = authed_client.get(f"/v1/program/context?workspace_id={ws_id}")
    assert r.status_code == 404


def test_two_workspaces_track_independent_interview_progress(admin_client) -> None:
    ws_a = _create_workspace(admin_client, "pm_fleet")
    ws_b = _create_workspace(admin_client, "content_creator")

    r = admin_client.post(
        f"/v1/program/interview/answer?workspace_id={ws_a}", json={"answer": "Program Alpha"}
    )
    assert r.status_code == 200
    assert r.json()["context"]["interview_step"] == 1

    # ws_b's own interview hasn't been touched -- independent state.
    r = admin_client.get(f"/v1/program/context?workspace_id={ws_b}")
    assert r.json()["context"]["interview_step"] == 0

    r = admin_client.post(
        f"/v1/program/interview/answer?workspace_id={ws_b}", json={"answer": "Cooking Channel"}
    )
    assert r.status_code == 200
    assert r.json()["context"]["interview_step"] == 1

    # ws_a is still at step 1, unaffected by ws_b's answer.
    r = admin_client.get(f"/v1/program/context?workspace_id={ws_a}")
    assert r.json()["context"]["interview_step"] == 1

    # And there is no third, global scope for either to leak into: a request
    # naming no workspace is refused rather than answered from "default" (#129).
    assert admin_client.get("/v1/program/context").status_code == 404


def test_answer_uses_the_workspaces_persona_specific_field_mapping(admin_client) -> None:
    """content_creator falls back to the generic script, whose first
    question maps to `program_name` just like pm_fleet's -- confirms the
    answer is actually routed through the resolved use_case's own script,
    not silently ignored."""
    ws_id = _create_workspace(admin_client, "content_creator")
    r = admin_client.post(
        f"/v1/program/interview/answer?workspace_id={ws_id}",
        json={"answer": "Garden Channel"},
    )
    assert r.status_code == 200
    assert r.json()["context"]["program_name"] == "Garden Channel"


def test_wizard_authored_persona_drives_the_interview_with_its_own_script(admin_client) -> None:
    """A PersonaWizard-authored persona with a custom interview script wins
    over the generic fallback -- end to end from POST .../persona-templates
    through the actual interview routes, not a unit test of the resolver
    alone."""
    r = admin_client.post(
        "/v1/workspaces/persona-templates",
        json={
            "id": "dinner_party",
            "display_name": "Dinner Party",
            "agents": [{"agent": "host", "role": "Greets guests", "skills": ["plan_menu"]}],
            "interview": [
                {"field": "program_name", "agent": "host", "question": "What's the occasion?"},
                {"field": "vibe", "question": "What vibe are we going for?"},
            ],
        },
    )
    assert r.status_code == 201

    ws_id = _create_workspace(admin_client, "dinner_party")
    r = admin_client.get(f"/v1/program/context?workspace_id={ws_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["interview"]["total_steps"] == 2
    assert body["interview"]["agent"] == "host"
    assert body["interview"]["question"] == "What's the occasion?"

    r = admin_client.post(
        f"/v1/program/interview/answer?workspace_id={ws_id}",
        json={"answer": "A birthday dinner"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["context"]["program_name"] == "A birthday dinner"
    assert body["interview"]["question"] == "What vibe are we going for?"

    r = admin_client.post(
        f"/v1/program/interview/answer?workspace_id={ws_id}",
        json={"answer": "Warm and playful"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["interview"]["complete"] is True
    assert any("vibe" in f and "Warm and playful" in f for f in body["context"]["facts"])
