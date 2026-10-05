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
        run_store=object(),
        # The composition builds one admitted model helper over these
        # canonical authorities, shared by boot and materialized Agents.
        capability_effects=object(),
        provider_registry=object(),
        llm_router=object(),
        a2a_delegator=object(),
        agents={},
    )


def _capture_runtime_seams(monkeypatch, container: SimpleNamespace) -> dict[str, object]:
    """Stub create_container/create_agents and return what the factory got."""
    captured: dict[str, object] = {}

    async def fake_create_container(config):
        container.config = config
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
        run_store=object(),
        capability_effects=object(),
        provider_registry=object(),
        llm_router=object(),
        a2a_delegator=object(),
    )
    captured: dict[str, object] = {}
    # The real Container always initializes `agents` to an empty dict and
    # hands that object to `_wire_hierarchy`; the fake mirrors the contract
    # the bridge is written against.
    wired_agents: dict[str, object] = {}
    container.agents = wired_agents

    async def fake_create_container(config):
        container.config = config
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
            maistro_model_bindings=[
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
    assert captured["a2a_delegator"] is container.a2a_delegator
    assert list(container.agents) == ["wired-agent"]
    assert bridge.container is container


@pytest.mark.asyncio
async def test_start_exposes_governed_egress_over_the_container_authorities(monkeypatch):
    """The runtime keeps one canonical model-chat authority for off-roster
    conductor work (#718).

    The demo task backend runs `run_task` outside the agent roster; the
    egress the bridge exposes must be built over the same Container effect
    context, provider registry, router and gateway endpoint the roster's
    model clients got, or that work would cross a second, unrecorded HTTP
    path while quota rows presented as complete.
    """
    container = _fake_container()
    captured = _capture_runtime_seams(monkeypatch, container)

    bridge = MaistroCoreBridge()
    await bridge.start(Settings(maistro_agents_dir="agents", litellm_api_base="http://gw.test/v1"))

    egress = bridge.governed_egress
    assert egress is not None
    # The same canonical authorities the Container wired.
    assert egress._effects is container.capability_effects
    assert egress._registry is container.provider_registry
    assert egress._router is container.llm_router
    # One gateway endpoint, shared with the roster's model clients rather
    # than rebuilt -- the two doors cannot drift onto different credentials.
    assert egress._endpoint is captured["admitted_calls"]._endpoint
    assert captured["llm"]._calls is captured["admitted_calls"]
    assert bridge.admitted_calls is captured["admitted_calls"]


@pytest.mark.asyncio
async def test_governed_egress_is_none_before_start() -> None:
    """The seam states its unstarted truth rather than manufacturing one."""
    assert MaistroCoreBridge().governed_egress is None


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
        run_store=object(),
        capability_effects=object(),
        provider_registry=object(),
        llm_router=object(),
        a2a_delegator=object(),
        agents=wired_agents,
    )

    async def fake_create_container(config):
        container.config = config
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
    from maistro.capabilities.model_chat import GovernedLLMClient

    assert isinstance(source.llm, GovernedLLMClient)
    assert source.llm._calls is bridge.admitted_calls
    assert source.llm._calls._egress._effects is container.capability_effects
    assert source.llm._calls._egress._registry is container.provider_registry
    assert source.llm._calls._egress._router is container.llm_router
    # The real shipped PREAMBLE template, not an empty stand-in.
    assert "governed dispatch and policy controls" in source.preamble


@pytest.mark.asyncio
async def test_start_carries_the_permission_grants_onto_the_container_config(monkeypatch):
    """The fail-closed Sentinel table (#1165) needs the operator's grants to
    reach `AgentConfig.security`, or no Conductor can ever authorize a tool."""
    container = _fake_container()
    captured: dict[str, object] = {}

    async def fake_create_container(config):
        container.config = config
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
async def test_start_carries_the_model_bindings_onto_the_container_config(monkeypatch):
    """#1079 Finding 1: the operator's `model.chat` Binding declarations need
    to reach `AgentConfig.model_bindings`, or `bootstrap_model_bindings()`
    always authorizes nothing and every governed model-egress node refuses
    every Binding in production."""
    from maistro.types.config import ModelBindingConfig

    container = _fake_container()
    captured: dict[str, object] = {}

    async def fake_create_container(config):
        container.config = config
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
            maistro_model_bindings=[
                ModelBindingConfig(binding_id="b1", project_id="p1", provider_name="gpt-4"),
            ],
        )
    )

    config = captured["config"]
    assert [b.binding_id for b in config.model_bindings] == ["b1"]
    assert config.model_bindings[0].provider_name == "gpt-4"


@pytest.mark.asyncio
async def test_start_parses_model_bindings_from_a_json_env_value(monkeypatch):
    """`MAISTRO_MODEL_BINDINGS` is JSON, like `MAISTRO_PERMISSIONS` -- the real
    `Settings` env parsing path, not a Python literal handed in directly."""
    from maistro.types.config import ModelBindingConfig

    monkeypatch.setenv(
        "MAISTRO_MODEL_BINDINGS",
        '[{"binding_id": "env-b1", "project_id": "env-p1", "provider_name": "gpt-4"}]',
    )

    settings = Settings(maistro_agents_dir="agents")

    assert settings.maistro_model_bindings == [
        ModelBindingConfig(binding_id="env-b1", project_id="env-p1", provider_name="gpt-4")
    ]


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
async def test_start_exposes_admitted_calls_over_configured_container(monkeypatch):
    from maistro.capabilities.admitted_model import AdmittedModelCalls

    container = _fake_container()
    _capture_runtime_seams(monkeypatch, container)
    bridge = MaistroCoreBridge()
    assert bridge.admitted_calls is None
    await bridge.start(
        Settings(
            maistro_agents_dir="agents",
            maistro_model_bindings=[{"binding_id": "operator-model", "project_id": "project"}],
        )
    )
    calls = bridge.admitted_calls
    assert isinstance(calls, AdmittedModelCalls)
    assert calls._runs is container.run_store
    assert calls._effects is container.capability_effects
    assert calls._binding_ids == ("operator-model",)


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_origin", ["boot", "materialized"])
async def test_configured_hive_agents_use_admitted_execution_and_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, agent_origin: str
) -> None:
    """The real composition must join Agent calls to declared, persisted authority.

    Provision the canonical scope in a local SQLite store before boot, just as
    an operator must know the Project ID when declaring a Binding. Both boots,
    the roster factory, later materialization, admission and execution are real;
    only the final provider HTTP transport is substituted. In particular, a
    domain TurnID must not replace the canonical RunID (#1956).
    """
    import json
    from datetime import UTC, datetime

    import httpx
    import services.agent_materialization as materialization
    import stores
    from models.schemas import Agent as AgentDefinition

    from maistro.capabilities.invocation import InvocationStatus
    from maistro.container import create_container
    from maistro.http import set_test_transport
    from maistro.runs.model import AttemptStatus, RunStatus
    from maistro.security._types import AuthContext
    from maistro.types.config import AgentConfig

    workspace_id = f"hive-{agent_origin}"
    actor_id = "authenticated-hive-owner"
    database_url = f"sqlite:///{tmp_path / 'canonical.db'}"
    provisioning = await create_container(
        AgentConfig(
            router_api_key="fixture-router-key",
            database_url=database_url,
            workspace_id=workspace_id,
        )
    )
    try:
        await provisioning.workspace_store.create(
            creator_user_id=actor_id, name="Hive admitted Agents", workspace_id=workspace_id
        )
        root = await provisioning.project_scope_store.root_for_workspace(workspace_id)
    finally:
        await provisioning.aclose()

    roster = tmp_path / "agents"
    (roster / "boot-agent").mkdir(parents=True)
    (roster / "PREAMBLE.md").write_text("Follow governed dispatch for {{name}}.\n")
    (roster / "boot-agent" / "SOUL.md").write_text("Answer the user's question clearly.")
    (roster / "boot-agent" / "agent.yaml").write_text(
        "name: boot-agent\nmodel: requested-alias\nreasoning:\n  strategy: direct\ntools: []\n"
    )
    provider_config = tmp_path / "providers.yaml"
    # A configured Binding pin needs operator-declared registry metadata (#1957).
    provider_config.write_text(
        "models:\n"
        "  - name: configured-hive-model\n"
        "    provider: fixture-provider\n"
        "    cost_input: 0.1\n"
        "    cost_output: 0.2\n"
        "    latency_p50_ms: 100\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    settings = Settings(
        maistro_agents_dir=str(roster),
        provider_config_path=str(provider_config),
        maistro_router_api_key="fixture-router-key",
        maistro_llm_api_key="configured-binding-key",
        hive_default_workspace_id=workspace_id,
        litellm_api_base="http://hive-gateway.fixture/v1",
        maistro_model_bindings=[
            {
                "binding_id": "operator-declared-hive-model",
                "project_id": root.project_id,
                "provider_name": "configured-hive-model",
            }
        ],
    )
    sent: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "model": "hive-provider-version",
                "choices": [{"message": {"role": "assistant", "content": "admitted answer"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    set_test_transport(httpx.MockTransport(transport))
    bridge = MaistroCoreBridge()
    materialized_id = f"admitted-fixture-{agent_origin}"
    try:
        await bridge.start(settings)
        container = bridge.container
        agent = container.agents["boot-agent"]
        if agent_origin == "materialized":
            definition = AgentDefinition(
                id=materialized_id,
                workspace_id=workspace_id,
                name="later-agent",
                model="requested-alias",
                status="idle",
                created_at=datetime.now(UTC),
                description="Answer questions clearly.",
                capabilities=[],
                config={"strategy": "direct", "soul": "Answer the user's question clearly."},
            )
            stored = await materialization.materialize_runtime(definition)
            assert stored.config["dispatchable"] is True
            agent = container.agents[definition.name]

        auth = AuthContext(user_id=actor_id, username="owner")
        messages = [{"role": "user", "content": "Say hello."}]
        run = await container._admit_chat_turn(messages, auth=auth, dispatch_pending=True)
        domain_turn_id = "session-domain-turn-not-a-canonical-run"
        assert run.run_id != domain_turn_id

        async def dispatch() -> dict[str, Any]:
            response = await agent.handle(messages, auth, turn_id=domain_turn_id)
            assert response.failed is False, response.error
            assert response.content == "admitted answer"
            return {"choices": [{"message": {"content": response.content}}]}

        result = await container._execute_chat_turn(run, messages, dispatch)
        await container._close_chat_run(run, result=result)
        nodes = await container.run_store.list_node_runs(run.run_id)
        assert len(nodes) == 1
        attempts = await container.run_store.list_attempts(nodes[0].node_run_id)
        assert len(attempts) == 1
        assert nodes[0].status is RunStatus.COMPLETED
        assert attempts[0].status is AttemptStatus.COMPLETED
        assert attempts[0].execution_lease is not None
        invocation_rows = await container.capability_effects.invocation_store.list_effect(
            run_id=run.run_id,
            node_run_id=nodes[0].node_run_id,
            binding_id="operator-declared-hive-model",
            effect_key=f"agent-llm:{agent.identity.name}:0:1",
        )
        assert len(invocation_rows) == 1
        invocation = invocation_rows[0]
        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.actor_id == run.actor_principal_id == actor_id
        assert invocation.binding.workspace_id == run.workspace_id == workspace_id
        assert invocation.binding.project_id == run.project_id == root.project_id
        assert invocation.binding.binding_id == "operator-declared-hive-model"
        assert invocation.run_id == run.run_id
        assert invocation.node_run_id == nodes[0].node_run_id
        assert invocation.attempt_id == attempts[0].attempt_id
        assert invocation.usage is not None
        assert invocation.usage.input_units == 7
        assert invocation.usage.output_units == 3
        events = container.usage_log.events_for("configured-hive-model")
        assert len(events) == 1
        assert events[0].invocation_id == invocation.invocation_id
        assert events[0].usage_reported is True
        assert (events[0].input_tokens, events[0].output_tokens) == (7, 3)
        assert len(sent) == 1
        assert sent[0].url == "http://hive-gateway.fixture/v1/chat/completions"
        assert sent[0].headers["Authorization"] == "Bearer configured-binding-key"
        assert json.loads(sent[0].content)["model"] == "configured-hive-model"
        # The boot and post-boot factory paths retain this composition's one
        # admitted helper instead of creating a second Binding authority.
        assert agent._llm is container.agents["boot-agent"]._llm
        assert agent._llm._calls is bridge.admitted_calls

        # A client retained by either factory cannot retain a grant after the
        # canonical Binding is revoked. A fresh, genuinely admitted execution
        # still refuses without a second HTTP call or usage record.
        await container.capability_effects.bindings.revoke("operator-declared-hive-model")
        refused_run = await container._admit_chat_turn(messages, auth=auth, dispatch_pending=True)

        async def dispatch_after_revocation() -> dict[str, Any]:
            response = await agent.handle(messages, auth, turn_id="another-domain-turn")
            assert response.failed is True
            return {"choices": [{"message": {"content": response.content}}]}

        await container._execute_chat_turn(refused_run, messages, dispatch_after_revocation)
        await container._close_chat_run(refused_run, error="binding_revoked")
        refused_nodes = await container.run_store.list_node_runs(refused_run.run_id)
        assert len(refused_nodes) == 1
        assert not await container.capability_effects.invocation_store.list_effect(
            run_id=refused_run.run_id,
            node_run_id=refused_nodes[0].node_run_id,
            binding_id="operator-declared-hive-model",
            effect_key=f"agent-llm:{agent.identity.name}:0:1",
        )
        assert len(sent) == 1
        assert container.usage_log.events_for("configured-hive-model") == events
    finally:
        set_test_transport(None)
        if bridge.container is not None:
            await bridge.container.aclose()
        if materialized_id in stores.agents:
            stores.agents.pop(materialized_id)
