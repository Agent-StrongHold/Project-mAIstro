"""Focused coverage for the Hive -> maistro-core composition adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from adapters.maistro_core import MaistroCoreBridge
from config import Settings


def _fake_container() -> SimpleNamespace:
    """The seams `_construct_runtime` reads off the wired Container."""
    return SimpleNamespace(
        prompt_manager=object(),
        context_assembly_policy=object(),
        context_builder=object(),
        warden=object(),
        sentinel=object(),
        learning_store=object(),
        learning_extractor=object(),
        outcome_store=object(),
        session_store=object(),
        quota_tracker=object(),
        agents={},
    )


def _capture_runtime_seams(monkeypatch, container: SimpleNamespace) -> dict[str, object]:
    """Stub create_container/create_agents and return what the factory got."""
    captured: dict[str, object] = {}

    async def fake_create_container(config):
        return container

    async def fake_create_agents(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr("maistro.container.create_container", fake_create_container)
    monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)
    monkeypatch.setattr("services.secrets.maistro_llm_api_key", lambda _settings: "")
    return captured


@pytest.mark.asyncio
async def test_start_passes_container_prompt_manager_to_agent_factory(monkeypatch):
    """Hive must consume the prompt store selected by the core Container (#122)."""
    selected_prompt_manager = object()
    selected_assembly_policy = object()
    container = SimpleNamespace(
        prompt_manager=selected_prompt_manager,
        context_assembly_policy=selected_assembly_policy,
        context_builder=object(),
        warden=object(),
        sentinel=object(),
        learning_store=object(),
        learning_extractor=object(),
        outcome_store=object(),
        session_store=object(),
        quota_tracker=object(),
    )
    captured: dict[str, object] = {}
    # The real Container always initializes `agents` to an empty dict and
    # hands that object to `_wire_hierarchy`; the fake mirrors the contract
    # the bridge is written against.
    wired_agents: dict[str, object] = {}
    container.agents = wired_agents

    async def fake_create_container(config):
        captured["config"] = config
        return container

    async def fake_create_agents(**kwargs):
        captured.update(kwargs)
        return {"wired-agent": SimpleNamespace(identity=None)}

    monkeypatch.setattr("maistro.container.create_container", fake_create_container)
    monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)
    monkeypatch.setattr("services.secrets.maistro_llm_api_key", lambda _settings: "")

    bridge = MaistroCoreBridge()
    await bridge.start(
        Settings(
            maistro_agents_dir="agents",
            litellm_api_base="http://localhost:4000/v1",
            provider_config_path="/etc/hive/providers.yaml",
            model_bindings=[
                {
                    "binding_id": "canvas-quality",
                    "project_id": "project-canvas",
                    "provider_name": "quality-model",
                }
            ],
        )
    )

    assert captured["prompt_manager"] is selected_prompt_manager
    config = captured["config"]
    assert config.provider_config_path == "/etc/hive/providers.yaml"
    assert config.model_bindings[0].binding_id == "canvas-quality"
    # Same requirement, one wiring later: the ADR-091 assembly the Container
    # selected has to be the one the agents get, or the Conductor's episodic
    # memories reach no prompt (#622).
    assert captured["context_assembly_policy"] is selected_assembly_policy
    assert list(container.agents) == ["wired-agent"]
    assert bridge.container is container


@pytest.mark.asyncio
async def test_start_resolves_a_relative_agents_dir_against_the_backend(monkeypatch):
    """A relative settings.maistro_agents_dir is resolved against the hive-
    conductor backend directory before it reaches the factory -- the arc the
    diff-coverage gate flagged half-taken: every other test here boots with
    one, but nothing pinned what the factory is actually handed."""
    import os

    container = _fake_container()
    captured = _capture_runtime_seams(monkeypatch, container)

    bridge = MaistroCoreBridge()
    await bridge.start(Settings(maistro_agents_dir="agents"))

    resolved = captured["agents_dir"]
    assert isinstance(resolved, str)
    assert os.path.isabs(resolved)
    assert os.path.basename(os.path.normpath(resolved)) == "agents"


@pytest.mark.asyncio
async def test_start_passes_an_absolute_agents_dir_through_untouched(monkeypatch, tmp_path):
    """An absolute settings.maistro_agents_dir needs no resolution: it must
    reach `create_agents` byte-for-byte, not joined onto the backend directory
    by the relative-branch fallback (the other half of line 156's branch)."""
    absolute_dir = str(tmp_path / "agents")
    # The construction now also retains the directory's PREAMBLE template for
    # the runtime-materialization seam (#840 Slice 4) -- the factory already
    # required it, so the fixture provides one.
    Path(absolute_dir).mkdir()
    (Path(absolute_dir) / "PREAMBLE.md").write_text("preamble for {{agent_name}}")
    container = _fake_container()
    captured = _capture_runtime_seams(monkeypatch, container)

    bridge = MaistroCoreBridge()
    await bridge.start(Settings(maistro_agents_dir=absolute_dir))

    assert captured["agents_dir"] == absolute_dir


@pytest.mark.asyncio
async def test_start_populates_the_dict_the_hierarchy_closed_over(monkeypatch):
    """The bridge must mutate the container's agents dict in place.

    `create_container` initializes an empty `agents` dict and hands that SAME
    object to `_wire_hierarchy`, whose `_AgentMapSource` resolves through the
    captured dict -- the closure captures the object, not its contents. The
    old code assigned a fresh dict (`container.agents = agents`), which left
    the hierarchy reading the original empty map forever: every hierarchical
    resolution would raise `HierarchyError("unknown local agent ...")` while
    `container.agents` itself looked fully populated.

    Proved against the REAL `_wire_hierarchy` closure, not a re-statement of
    it: wire the fake container's dict through maistro's own wiring, start the
    bridge, and resolve a roster name through the closure the way the ADR-101
    orchestrator does.
    """
    from maistro.container import _wire_hierarchy
    from maistro.skills.registry import InMemorySkillRegistry

    # The dict the container wired: `_wire_hierarchy` closes over exactly this
    # object, before any agent exists in it.
    wired_agents: dict[str, Any] = {}
    _registry, orchestrator = _wire_hierarchy(wired_agents, InMemorySkillRegistry())

    roster_agent = SimpleNamespace(identity=SimpleNamespace(name="delivery", skills=()))
    container = SimpleNamespace(
        prompt_manager=object(),
        context_assembly_policy=object(),
        context_builder=object(),
        warden=object(),
        sentinel=object(),
        learning_store=object(),
        learning_extractor=object(),
        outcome_store=object(),
        session_store=object(),
        quota_tracker=object(),
        agents=wired_agents,
    )

    async def fake_create_container(config):
        return container

    async def fake_create_agents(**kwargs):
        return {"delivery": roster_agent}

    monkeypatch.setattr("maistro.container.create_container", fake_create_container)
    monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)
    monkeypatch.setattr("services.secrets.maistro_llm_api_key", lambda _settings: "")

    bridge = MaistroCoreBridge()
    await bridge.start(Settings(maistro_agents_dir="agents"))

    # The wired map is still the wired map: populated in place, never replaced.
    assert bridge.container.agents is wired_agents
    assert bridge.container.agents is container.agents
    assert set(bridge.container.agents) == {"delivery"}

    # And the closure that the container built BEFORE the roster existed now
    # resolves it -- which the old rebinding silently broke.
    identity, _skills = await orchestrator._agent_source.resolve("delivery")
    assert identity.name == "delivery"


@pytest.mark.asyncio
async def test_start_registers_the_runtime_materialization_source(monkeypatch):
    """The bridge hands the runtime it built to the materialization service
    (#840 Slice 4): definitions created after boot (Forge, chat tools)
    materialize into THIS container's wired map, behind the same PREAMBLE the
    boot roster was seeded with."""
    from pathlib import Path

    import services.agent_materialization as materialization

    shipped_agents_dir = Path(__file__).resolve().parents[4] / "agents"
    container = _fake_container()
    _capture_runtime_seams(monkeypatch, container)

    bridge = MaistroCoreBridge()
    await bridge.start(Settings(maistro_agents_dir=str(shipped_agents_dir)))

    source = materialization._runtime_source
    assert source is not None
    assert source.container is container
    assert source.llm is not None
    # The real shipped PREAMBLE template, not an empty stand-in.
    assert "governed dispatch and policy controls" in source.preamble
