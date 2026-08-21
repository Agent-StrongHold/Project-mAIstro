"""services/agent_materialization.py -- Persona/Workspace system: the
missing wiring between maistro.personas.expander.expand_persona() and
hive-conductor's stores.agents. Every persona is treated identically here
-- pm_fleet is just one premade template, not special-cased.
"""

from __future__ import annotations

import pytest
import stores
from services.agent_materialization import (
    agent_id_for,
    materialize_workspace_agents,
    workspace_agents,
)

from maistro.personas.schema import PersonaTemplate, SpawnSpec


@pytest.fixture(autouse=True)
def _clear_agents():
    for key in list(stores.agents.keys()):
        stores.agents.pop(key, None)
    yield
    for key in list(stores.agents.keys()):
        stores.agents.pop(key, None)


def _template(**overrides) -> PersonaTemplate:
    defaults = {
        "kind": "workspace",
        "id": "dinner_party",
        "spawns": [
            SpawnSpec(agent="host", role="Greets guests", tools=["send_message"], skills=[]),
            SpawnSpec(agent="chef", role="Plans the menu", tools=[], skills=["plan_menu"]),
        ],
    }
    defaults.update(overrides)
    return PersonaTemplate(**defaults)


def test_materializes_one_agent_per_spawn() -> None:
    agents = materialize_workspace_agents("ws-1", _template())
    assert {a.name for a in agents} == {"dinner_party.host", "dinner_party.chef"}
    assert all(a.workspace_id == "ws-1" for a in agents)


def test_writes_into_stores_agents() -> None:
    materialize_workspace_agents("ws-1", _template())
    assert len(workspace_agents("ws-1")) == 2


def test_agent_id_is_deterministic_and_workspace_scoped() -> None:
    assert agent_id_for("ws-1", "host") == "ws-1.host"
    materialize_workspace_agents("ws-1", _template())
    assert "ws-1.host" in stores.agents
    assert "ws-1.chef" in stores.agents


def test_rematerializing_overwrites_not_duplicates() -> None:
    materialize_workspace_agents("ws-1", _template())
    materialize_workspace_agents("ws-1", _template())
    assert len(workspace_agents("ws-1")) == 2


def test_capabilities_and_skills_come_from_the_spawn() -> None:
    agents = materialize_workspace_agents("ws-1", _template())
    host = next(a for a in agents if a.name == "dinner_party.host")
    chef = next(a for a in agents if a.name == "dinner_party.chef")
    assert host.capabilities == ["send_message"]
    assert chef.skills == ["plan_menu"]


def test_two_workspaces_of_the_same_persona_get_independent_agents() -> None:
    materialize_workspace_agents("ws-a", _template())
    materialize_workspace_agents("ws-b", _template())
    assert {a.id for a in workspace_agents("ws-a")} == {"ws-a.host", "ws-a.chef"}
    assert {a.id for a in workspace_agents("ws-b")} == {"ws-b.host", "ws-b.chef"}


def test_department_kind_template_materializes_nothing() -> None:
    template = PersonaTemplate(kind="department", id="evals_only")
    assert materialize_workspace_agents("ws-1", template) == []
    assert workspace_agents("ws-1") == []


def test_content_creator_and_pm_fleet_both_materialize_the_same_way() -> None:
    """No special-casing: any persona's spawns become real agents through
    the exact same path."""
    content_creator = _template(
        id="content_creator",
        spawns=[SpawnSpec(agent="ideation", tools=[], skills=["suggest_topics"])],
    )
    pm_fleet = _template(
        id="pm_fleet", spawns=[SpawnSpec(agent="intake", tools=["create_epic"], skills=[])]
    )
    materialize_workspace_agents("ws-cc", content_creator)
    materialize_workspace_agents("ws-pm", pm_fleet)
    assert workspace_agents("ws-cc")[0].name == "content_creator.ideation"
    assert workspace_agents("ws-pm")[0].name == "pm_fleet.intake"
