"""#2549 Slice C: the PM-demo persona is picker-gated behind `pm_tooling`.

The UAT product direction (#2549): the standard product carries no
project-management demo surfaces. The `pm_fleet` persona therefore leaves
the workspace-creation picker unless setup selected the explicit `pm_tooling`
optional module — while existing pm_fleet workspaces keep resolving (the gate
is a picker filter, never a resolution or membership check) and the
per-template agent/checklist routes stay template-agnostic.

Read seam under test: `services.optional_modules.picker_hidden_template_ids`
over the durable setup record (`stores.sessions["__hive_setup__"]`), read
through `identity_health.setup_state` — the same record and store seam
`identity_health` reads for `crypto_identity`.
"""

from __future__ import annotations

import pytest
import stores
from services.identity_health import SETUP_STATE_KEY


@pytest.fixture(autouse=True)
def _clean_setup_record():
    """Keep the durable setup record pristine around each case.

    `stores.sessions` is process-global in memory mode, so a record one case
    seeds must not leak into another suite's assumptions.
    """
    real_sessions = stores.sessions
    existed = SETUP_STATE_KEY in real_sessions
    saved = real_sessions.get(SETUP_STATE_KEY)
    if existed:
        real_sessions.pop(SETUP_STATE_KEY, None)
    yield
    # A case may have monkeypatched `stores.sessions` with an unreadable
    # stand-in; put the real store back before touching keys, so teardown
    # works regardless of finalization order against monkeypatch's undo.
    stores.sessions = real_sessions
    if existed:
        real_sessions[SETUP_STATE_KEY] = saved
    elif SETUP_STATE_KEY in real_sessions:
        real_sessions.pop(SETUP_STATE_KEY, None)


def _picker_ids(admin_client) -> set[str]:
    r = admin_client.get("/v1/workspaces/persona-templates")
    assert r.status_code == 200
    return {opt["id"] for opt in r.json()}


def test_pm_fleet_absent_from_picker_without_the_module(admin_client) -> None:
    """No setup record (factory-fresh deployment): pm_fleet is not offered."""
    ids = _picker_ids(admin_client)
    assert "pm_fleet" not in ids
    # The filter hides the gated persona, not the picker: an ungated shipped
    # persona is still offered, so a fresh install can still create a
    # workspace from the dialog.
    assert "content_creator" in ids


def test_setup_without_pm_tooling_keeps_the_persona_hidden(admin_client) -> None:
    """A completed setup that did not select `pm_tooling` keeps it hidden."""
    stores.sessions[SETUP_STATE_KEY] = {"optional_modules": ["crypto_identity"]}
    assert "pm_fleet" not in _picker_ids(admin_client)


def test_selecting_pm_tooling_restores_the_persona(admin_client) -> None:
    stores.sessions[SETUP_STATE_KEY] = {"optional_modules": ["crypto_identity", "pm_tooling"]}
    assert "pm_fleet" in _picker_ids(admin_client)


def test_gate_is_picker_only_existing_pm_fleet_workspace_still_resolves(
    admin_client,
) -> None:
    """A workspace created before the gate keeps resolving its persona.

    Demotion must not strand the installed base: per-template routes and
    workspace creation stay template-agnostic even while the picker hides
    the persona.
    """
    r_create = admin_client.post(
        "/v1/workspaces",
        json={"persona_template_id": "pm_fleet", "name": "Legacy PM WS"},
    )
    assert r_create.status_code == 201
    ws_id = r_create.json()["id"]

    # Per-template agents route (WorkspaceToolBindings / persona picker options).
    r_agents = admin_client.get("/v1/workspaces/persona-templates/pm_fleet/agents")
    assert r_agents.status_code == 200

    # And the workspace itself still resolves with the gated persona.
    r_get = admin_client.get(f"/v1/workspaces/{ws_id}")
    assert r_get.status_code == 200
    assert r_get.json()["persona_template_id"] == "pm_fleet"


def test_picker_filter_fails_closed_when_setup_record_is_unreadable(
    admin_client, monkeypatch
) -> None:
    """A corrupt setup record hides gated personas rather than showing them."""
    import routes.workspaces as workspaces_routes
    import services.optional_modules as om

    class _Boom:
        def get(self, _key: str) -> dict[str, object]:
            raise RuntimeError("store unavailable")

    monkeypatch.setattr(stores, "sessions", _Boom())
    assert om.enabled_modules() == []
    assert "pm_fleet" in om.picker_hidden_template_ids()
    assert "pm_fleet" not in {opt.id for opt in workspaces_routes.list_persona_templates()}
