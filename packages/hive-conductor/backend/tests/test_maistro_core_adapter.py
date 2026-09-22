"""Focused coverage for the Hive -> maistro-core composition adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from adapters.maistro_core import MaistroCoreBridge
from config import Settings


class _FakeBindings:
    """Minimal canonical BindingStore double for stubbed containers."""

    def __init__(self) -> None:
        self.put_calls: list[object] = []

    async def put(self, binding: object) -> object:
        self.put_calls.append(binding)
        return binding


async def _fake_create_root(workspace_id: str) -> SimpleNamespace:
    return SimpleNamespace(project_id=f"root-of-{workspace_id}")


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
        project_scope_store=SimpleNamespace(create_root=_fake_create_root),
        capability_effects=SimpleNamespace(bindings=_FakeBindings()),
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
        project_scope_store=SimpleNamespace(create_root=_fake_create_root),
        capability_effects=SimpleNamespace(bindings=_FakeBindings()),
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
        )
    )

    assert captured["prompt_manager"] is selected_prompt_manager
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
        project_scope_store=SimpleNamespace(create_root=_fake_create_root),
        capability_effects=SimpleNamespace(bindings=_FakeBindings()),
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


@pytest.mark.asyncio
async def test_start_carries_the_permission_grants_onto_the_container_config(monkeypatch):
    """The fail-closed Sentinel table (#1165) needs the operator's grants to
    reach `AgentConfig.security`, or no Conductor can ever authorize a tool."""
    container = _fake_container()
    captured: dict[str, object] = {}

    async def fake_create_container(config):
        captured["config"] = config
        return container

    async def fake_create_agents(**kwargs):
        return {"wired-agent": SimpleNamespace(identity=None)}

    monkeypatch.setattr("maistro.container.create_container", fake_create_container)
    monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)
    monkeypatch.setattr("services.secrets.maistro_llm_api_key", lambda _settings: "")

    await MaistroCoreBridge().start(
        Settings(
            maistro_agents_dir="agents",
            maistro_permission_preset="dangerous_tools_admin",
            maistro_permissions={"shell": ["admin"]},
        )
    )

    config = captured["config"]
    assert config.security.permission_preset == "dangerous_tools_admin"
    assert config.security.permissions == {"shell": ["admin"]}


@pytest.mark.asyncio
async def test_route_passes_the_caller_identity_through_to_the_container() -> None:
    """A caller's principal reaches `Container.route_request`; nothing else is
    invented on the way (the Container itself substitutes anonymous for None)."""
    captured: dict[str, object] = {}

    class _Container:
        async def route_request(self, messages, **kwargs):
            captured.update(kwargs)
            return {"content": "ok"}

    bridge = MaistroCoreBridge()
    bridge._container = _Container()
    principal = object()

    assert await bridge.route([{"role": "user", "content": "hi"}], auth=principal) == {
        "content": "ok"
    }
    assert captured["auth"] is principal
    assert await bridge.route([{"role": "user", "content": "hi"}]) == {"content": "ok"}
    assert captured["auth"] is None


@pytest.mark.asyncio
async def test_start_provisions_the_declared_default_model_binding(monkeypatch):
    """#1085: the production bridge, not a test, provisions the operator's
    declared model.chat Binding into the canonical store.

    The Binding is scoped to the default Workspace's Root Project -- the scope
    `authorize_hive_dag_scope` admits DAG runs into when no Project is
    selected -- so a stored DAG model node that predates binding ids can
    resolve a governed Invocation in the real bridge composition instead of
    failing for want of a Binding no operator could declare.
    """
    from maistro.capabilities.providers.llm_gateway import MODEL_CHAT_CAPABILITY

    async def fake_create_agents(**kwargs: object) -> dict[str, object]:
        return {"wired-agent": SimpleNamespace(identity=None)}

    monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)
    monkeypatch.setattr("services.secrets.maistro_llm_api_key", lambda _settings: "")
    # The declaration the boot actually consumed: the PASSED Settings object.
    # The ambient environment deliberately carries nothing -- a passed
    # declaration that only the bridge saw must still reach node resolution
    # through the composed runtime config (#1085), which is exactly the split
    # this test pins shut.
    monkeypatch.delenv("MAISTRO_MODEL_BINDING_ID", raising=False)

    bridge = MaistroCoreBridge()
    await bridge.start(
        Settings(
            maistro_agents_dir="agents",
            litellm_api_base="http://localhost:4000/v1",
            maistro_router_api_key="test-key",
            maistro_model_binding_id="hive-default-model",
        )
    )

    container = bridge.container
    assert container is not None
    # One authority: the composed runtime config carries the declaration the
    # boot provisioned from, and the canonical DAG runner forwards that same
    # value into every node's wiring.
    assert container.config.default_model_binding_id == "hive-default-model"
    root = await container.project_scope_store.root_for_workspace("default")
    binding = await container.capability_effects.bindings.resolve(
        "hive-default-model",
        workspace_id="default",
        project_id=root.project_id,
        node_id="any-node",
        capability=MODEL_CHAT_CAPABILITY,
    )
    assert binding.capability == MODEL_CHAT_CAPABILITY
    assert binding.workspace_id == "default"
    assert binding.project_id == root.project_id

    # The same production composition must execute: a stored DAG model node
    # with no explicit binding_id runs through the real facade and canonical
    # durable Run path using only the binding the bridge provisioned, and the
    # resulting Invocation names that Run/NodeRun/Attempt (#1085 acceptance).
    import httpx
    import services.canonical_dag_runner as canonical
    import services.graph_runner as facade
    from services.dag_execution_scope import DagExecutionScope

    class _Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "model": "legacy-model-v2",
                "choices": [{"message": {"content": "bridge answer"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            }

    class _Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> _Response:
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(canonical, "_container", lambda: container)
    monkeypatch.setattr(canonical, "get_run_store", lambda: container.graph_run_store)

    result = await facade.execute_dag(
        {
            "id": "bridge-governed",
            "name": "bridge-governed",
            "description": "bridge task",
            "nodes": [
                {
                    "id": "n1",
                    "name": "worker",
                    "model": "legacy-model",
                    "config": {"execution_tier": "safe"},
                }
            ],
            "edges": [],
        },
        scope=DagExecutionScope(
            workspace_id="default", project_id=root.project_id, user_id="bridge-user"
        ),
    )

    assert result["status"] == "completed"
    invocations = list(
        container.capability_effects.invocation_store._items.values()  # type: ignore[attr-defined]
    )
    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.binding.binding_id == "hive-default-model"
    assert invocation.workspace_id == "default"
    assert invocation.project_id == root.project_id
    assert invocation.run_id == result["run_id"]
    assert invocation.node_run_id
    assert invocation.attempt_id
    node_runs = await container.run_store.list_node_runs(result["run_id"])
    assert [node_run.node_run_id for node_run in node_runs] == [invocation.node_run_id]
    attempts = await container.run_store.list_attempts(invocation.node_run_id)
    assert [attempt.attempt_id for attempt in attempts] == [invocation.attempt_id]
    assert invocation.usage is not None
    assert invocation.usage.provider
    assert invocation.usage.model_version == "legacy-model-v2"


@pytest.mark.asyncio
async def test_start_without_a_binding_declaration_provisions_nothing(monkeypatch):
    """#1085 fail-closed default: an operator who declares no default binding
    gets none. The shipped default is empty -- the bridge never mints the
    authorization on the operator's behalf -- so a stored DAG model node that
    names no binding fails closed through the real facade instead of executing
    on an implicit grant, and no Invocation is ever started."""

    async def fake_create_agents(**kwargs: object) -> dict[str, object]:
        return {"wired-agent": SimpleNamespace(identity=None)}

    monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)
    monkeypatch.setattr("services.secrets.maistro_llm_api_key", lambda _settings: "")
    monkeypatch.delenv("MAISTRO_MODEL_BINDING_ID", raising=False)

    # No maistro_model_binding_id: this is exactly what an operator who
    # configured nothing ships with.
    assert Settings().maistro_model_binding_id == ""

    bridge = MaistroCoreBridge()
    await bridge.start(
        Settings(
            maistro_agents_dir="agents",
            litellm_api_base="http://localhost:4000/v1",
            maistro_router_api_key="test-key",
        )
    )

    container = bridge.container
    assert container is not None
    assert await container.capability_effects.bindings.get("hive-default-model") is None

    # The same production composition must refuse: a stored DAG model node
    # with no explicit binding_id and no deployment declaration cannot
    # authorize a model effect, so the canonical Run fails truthfully and no
    # Invocation exists (#1085 acceptance: compatibility adapters cannot
    # report success from an effect they were never authorized to make).
    import services.canonical_dag_runner as canonical
    import services.graph_runner as facade
    from services.dag_execution_scope import DagExecutionScope

    root = await container.project_scope_store.create_root("default")
    monkeypatch.setattr(canonical, "_container", lambda: container)
    monkeypatch.setattr(canonical, "get_run_store", lambda: container.graph_run_store)

    from services.graph_runner import CanonicalDagExecutionError

    with pytest.raises(CanonicalDagExecutionError, match="binding") as excinfo:
        await facade.execute_dag(
            {
                "id": "bridge-undeclared",
                "name": "bridge-undeclared",
                "description": "undeclared task",
                "nodes": [
                    {
                        "id": "n1",
                        "name": "worker",
                        "model": "legacy-model",
                        "config": {"execution_tier": "safe"},
                    }
                ],
                "edges": [],
            },
            scope=DagExecutionScope(
                workspace_id="default", project_id=root.project_id, user_id="bridge-user"
            ),
        )

    result = excinfo.value.result
    assert result["status"] == "failed"
    invocations = list(
        container.capability_effects.invocation_store._items.values()  # type: ignore[attr-defined]
    )
    assert invocations == []
