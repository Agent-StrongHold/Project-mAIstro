"""services/workspace_mode.py -- Persona/Workspace system, Phase H.

See the module docstring for the boundary #129 drew between the per-request
gates (retired onto workspace membership) and the boot-time defaults that keep
reading `HIVE_POC_MODE`, and for why no persona -- pm_fleet included -- is
special-cased by identity anywhere here.
"""

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
    persona's workspace authorizes its own members the same way.

    Every "falls back to the legacy flag" case became a refusal in #129. The
    environment variable is no longer reachable from any request, so these
    tests patch nothing: whatever `HIVE_POC_MODE` is set to while the suite
    runs, the answers below do not move.
    """

    def test_member_of_a_real_workspace_is_authorized(self) -> None:
        stores.workspaces["ws-1"] = _workspace(persona_template_id="content_creator")
        assert is_workspace_request_authorized("admin", "ws-1") is True

    def test_a_non_member_is_refused(self, monkeypatch) -> None:
        stores.workspaces["ws-1"] = _workspace()
        monkeypatch.setenv("HIVE_POC_MODE", "pm")
        monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
        assert is_workspace_request_authorized("someone-else", "ws-1") is False

    def test_no_workspace_id_is_refused(self, monkeypatch) -> None:
        monkeypatch.setenv("HIVE_POC_MODE", "pm")
        monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
        assert is_workspace_request_authorized("admin", None) is False

    def test_unknown_workspace_id_is_refused(self, monkeypatch) -> None:
        monkeypatch.setenv("HIVE_POC_MODE", "pm")
        monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
        assert is_workspace_request_authorized("admin", "does-not-exist") is False


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
