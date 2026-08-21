"""services/workspace_mode.py -- Persona/Workspace system, Phase H. See the
module docstring for the bounded scope of the call-site migration (which
gates were safely, mechanically re-pointable vs. which weren't), and for
why no persona (including pm_fleet) is special-cased by identity anywhere
here."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import stores
from models.schemas import Agent
from models.workspace import Workspace, WorkspaceMember
from services.workspace_mode import is_workspace_request_authorized, workspace_has_pm_fleet_agents


@pytest.fixture(autouse=True)
def _clear_state():
    for store in (stores.workspaces, stores.agents):
        for key in list(store.keys()):
            store.pop(key, None)
    yield
    for store in (stores.workspaces, stores.agents):
        for key in list(store.keys()):
            store.pop(key, None)


def _workspace(workspace_id: str = "ws-1", persona_template_id: str = "pm_fleet") -> Workspace:
    t = datetime.now(UTC)
    return Workspace(
        id=workspace_id,
        persona_template_id=persona_template_id,
        name="test",
        members=[WorkspaceMember(user_id="admin", role="owner")],
        created_at=t,
        updated_at=t,
    )


def _agent(workspace_id: str, name: str) -> Agent:
    t = datetime.now(UTC)
    return Agent(
        id=f"{workspace_id}.{name}",
        workspace_id=workspace_id,
        name=f"whatever.{name}",
        description="",
        model="x",
        status="idle",
        created_at=t,
    )


class TestIsWorkspaceRequestAuthorized:
    """Pure membership check, no persona-identity distinction -- any
    persona's workspace authorizes its own members the same way."""

    def test_member_of_a_real_workspace_is_authorized(self, monkeypatch) -> None:
        stores.workspaces["ws-1"] = _workspace(persona_template_id="content_creator")
        monkeypatch.setattr("services.workspace_mode.is_pm_poc_mode", lambda: False)
        assert is_workspace_request_authorized("admin", "ws-1") is True

    def test_non_member_falls_back_to_legacy_flag(self, monkeypatch) -> None:
        stores.workspaces["ws-1"] = _workspace()
        monkeypatch.setattr("services.workspace_mode.is_pm_poc_mode", lambda: False)
        assert is_workspace_request_authorized("someone-else", "ws-1") is False
        monkeypatch.setattr("services.workspace_mode.is_pm_poc_mode", lambda: True)
        assert is_workspace_request_authorized("someone-else", "ws-1") is True

    def test_no_workspace_id_falls_back_to_legacy_flag(self, monkeypatch) -> None:
        monkeypatch.setattr("services.workspace_mode.is_pm_poc_mode", lambda: True)
        assert is_workspace_request_authorized("admin", None) is True
        monkeypatch.setattr("services.workspace_mode.is_pm_poc_mode", lambda: False)
        assert is_workspace_request_authorized("admin", None) is False

    def test_unknown_workspace_id_falls_back_to_legacy_flag(self, monkeypatch) -> None:
        monkeypatch.setattr("services.workspace_mode.is_pm_poc_mode", lambda: True)
        assert is_workspace_request_authorized("admin", "does-not-exist") is True


class TestWorkspaceHasPmFleetAgents:
    """Data-driven: derived from the workspace's own materialized agent
    roster, not a `persona_template_id == "pm_fleet"` identity check."""

    def test_true_when_materialized_agents_include_a_pm_fleet_shaped_name(self) -> None:
        stores.agents["ws-1.intake"] = _agent("ws-1", "intake")
        assert workspace_has_pm_fleet_agents("ws-1") is True

    def test_false_when_no_materialized_agents_match(self) -> None:
        stores.agents["ws-1.ideation"] = _agent("ws-1", "ideation")
        assert workspace_has_pm_fleet_agents("ws-1") is False

    def test_false_when_workspace_has_no_materialized_agents_at_all(self) -> None:
        assert workspace_has_pm_fleet_agents("ws-1") is False

    def test_any_persona_declaring_pm_fleet_shaped_agents_qualifies(self) -> None:
        """Not identity-based: a hypothetically-named persona whose spawns
        happen to include e.g. "program_manager" qualifies the same way
        pm_fleet.yaml does -- nothing here checks persona_template_id."""
        stores.agents["ws-1.program_manager"] = _agent("ws-1", "program_manager")
        assert workspace_has_pm_fleet_agents("ws-1") is True

    def test_only_checks_the_given_workspaces_own_agents(self) -> None:
        stores.agents["ws-2.intake"] = _agent("ws-2", "intake")
        assert workspace_has_pm_fleet_agents("ws-1") is False
