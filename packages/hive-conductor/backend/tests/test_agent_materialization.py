"""services/agent_materialization.py -- Persona/Workspace system: the
missing wiring between maistro.personas.expander.expand_persona() and
hive-conductor's stores.agents. Every persona is treated identically here
-- pm_fleet is just one premade template, not special-cased.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
import stores
from models.schemas import Agent
from services.agent_materialization import (
    MANIFEST_ROSTER_SOURCE,
    agent_id_for,
    materialize_boot_roster,
    materialize_manifest_roster,
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


# ─── Canonical roster materialization (#840 Slice 3) ──────────────────────


def _manifest_agent(
    name: str,
    *,
    description: str = "",
    model: str = "auto",
    tools: tuple[str, ...] = (),
    skills: tuple[str, ...] = (),
) -> SimpleNamespace:
    """A roster entry shaped exactly as the factory builds one: a runtime
    Agent whose `identity` carries the manifest's declared fields."""
    return SimpleNamespace(
        identity=SimpleNamespace(
            name=name, description=description, model=model, tools=tools, skills=skills
        )
    )


_CANONICAL = ("delivery", "intake", "program_manager", "reporting", "risk_dependency")


def _canonical_roster() -> dict[str, SimpleNamespace]:
    return {
        name: _manifest_agent(name, tools=("poll_jira",) if name == "delivery" else ())
        for name in _CANONICAL
    }


class TestManifestRosterMaterialization:
    def test_boot_with_a_bridge_projects_the_canonical_roster_as_global_rows(self) -> None:
        materialize_manifest_roster(_canonical_roster())

        global_rows = [a for a in stores.agents.values() if a.workspace_id is None]
        # The set of global rows equals the canonical roster, name-keyed.
        assert {a.id for a in global_rows} == set(_CANONICAL)
        # Capabilities come from the identity's tools, the same mapping
        # persona materialization uses, so the capability union stays one
        # contract for `resolve_agent_task` / `pulse_roster`.
        assert stores.agents["delivery"].capabilities == ["poll_jira"]
        assert stores.agents["intake"].capabilities == []
        # From a bridge container the roster is dispatchable and stamped.
        assert stores.agents["delivery"].config["dispatchable"] is True
        assert stores.agents["delivery"].config["provenance"]["source"] == MANIFEST_ROSTER_SOURCE

    def test_materializing_twice_yields_one_row_per_agent(self) -> None:
        materialize_manifest_roster(_canonical_roster())
        created_at = stores.agents["delivery"].created_at

        materialize_manifest_roster(_canonical_roster())

        global_ids = [a.id for a in stores.agents.values() if a.workspace_id is None]
        assert sorted(global_ids) == sorted(_CANONICAL)
        # The upsert refreshed the projection in place.
        assert stores.agents["delivery"].created_at == created_at

    def test_stale_projected_rows_are_reaped_and_foreign_rows_are_not(self) -> None:
        roster = dict(_canonical_roster())
        roster["retired"] = _manifest_agent("retired")
        materialize_manifest_roster(roster)
        t = stores.now()
        stores.agents["chat-user-made"] = Agent(
            id="chat-user-made",
            name="user made",
            description="",
            model="x",
            status="idle",
            created_at=t,
        )

        # The roster no longer declares `retired`; the user row is not ours.
        materialize_manifest_roster(_canonical_roster())

        assert "retired" not in stores.agents
        assert "chat-user-made" in stores.agents
        assert set(_CANONICAL) <= set(stores.agents.keys())

    def test_rows_without_a_bridge_are_marked_non_dispatchable(self) -> None:
        """No maistro-core bridge, no runtime behind the row -- say so instead
        of wearing the shape of an executable roster (StubAgentPort honesty)."""
        materialize_manifest_roster({"delivery": _manifest_agent("delivery")}, dispatchable=False)
        assert stores.agents["delivery"].config["dispatchable"] is False


class TestBootRosterSeam:
    async def test_boot_with_a_bridge_materializes_its_container_roster(self) -> None:
        container = SimpleNamespace(agents=_canonical_roster())
        port = SimpleNamespace(container=container)

        rows = await materialize_boot_roster(
            SimpleNamespace(hive_mode="production", maistro_agents_dir="agents"), port
        )

        assert rows is not None  # production mode materializes; only demo/POC no-op
        assert [r.id for r in rows] == sorted(_CANONICAL)
        assert stores.agents["delivery"].config["dispatchable"] is True

    async def test_boot_without_a_bridge_builds_the_roster_and_marks_it_non_dispatchable(
        self, monkeypatch
    ) -> None:
        async def fake_build(settings):
            return {"delivery": _manifest_agent("delivery")}

        monkeypatch.setattr("adapters.maistro_core.build_canonical_roster", fake_build)

        rows = await materialize_boot_roster(
            SimpleNamespace(hive_mode="production", maistro_agents_dir="agents"),
            SimpleNamespace(),  # the stub port: no container
        )

        assert rows is not None
        assert [r.id for r in rows] == ["delivery"]
        assert stores.agents["delivery"].config["dispatchable"] is False

    async def test_a_roster_that_cannot_be_built_stores_nothing(self, monkeypatch) -> None:
        """Fail-closed: no roster -> no rows, and the fabricated demo rows
        never appear as a side effect."""

        async def boom(settings):
            raise RuntimeError("required agents directory agents was not found")

        monkeypatch.setattr("adapters.maistro_core.build_canonical_roster", boom)

        rows = await materialize_boot_roster(
            SimpleNamespace(hive_mode="production", maistro_agents_dir="agents"),
            SimpleNamespace(),
        )

        assert rows == []
        assert len(stores.agents) == 0

    async def test_the_real_construction_fails_closed_without_what_it_needs(self) -> None:
        """The fallback builds the roster the way the bridge does -- so it
        inherits the factory's and container's fail-closed contract rather
        than a softer one."""
        from adapters.maistro_core import build_canonical_roster
        from config import Settings

        with pytest.raises(Exception, match="ROUTER_API_KEY"):
            await build_canonical_roster(Settings(maistro_agents_dir="agents"))

    async def test_demo_and_pm_poc_modes_are_a_no_op(self, monkeypatch) -> None:
        assert (
            await materialize_boot_roster(
                SimpleNamespace(hive_mode="demo", maistro_agents_dir="agents"),
                SimpleNamespace(container=SimpleNamespace(agents=_canonical_roster())),
            )
            is None
        )
        monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
        assert (
            await materialize_boot_roster(
                SimpleNamespace(hive_mode="production", maistro_agents_dir="agents"),
                SimpleNamespace(container=SimpleNamespace(agents=_canonical_roster())),
            )
            is None
        )
        assert len(stores.agents) == 0


class TestDemoSeedGating:
    """`_seed_agents` used to seed whenever the store was empty; #840 scopes
    the fabricated roster to demo mode and moves the real roster to boot
    materialization."""

    def test_non_demo_boots_without_demo_rows(self) -> None:
        for key in list(stores.agents.keys()):
            stores.agents.pop(key, None)

        stores.initialize_stores()

        assert not any(re.fullmatch(r"agent-\d+", a.id) for a in stores.agents.values())
        # No fabricated counters either (234/189/156/... from the old seed).
        assert not any(a.tasks_completed for a in stores.agents.values())

    def test_demo_mode_still_seeds(self, monkeypatch) -> None:
        for key in list(stores.agents.keys()):
            stores.agents.pop(key, None)
        monkeypatch.setattr("config.get_settings", lambda: SimpleNamespace(hive_mode="demo"))

        stores._seed_agents()

        assert {f"agent-{i}" for i in range(1, 10)} <= set(stores.agents.keys())
