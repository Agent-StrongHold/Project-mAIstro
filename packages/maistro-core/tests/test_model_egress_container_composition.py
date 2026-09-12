"""Production-composition proof for governed model egress (#1079)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
from maistro.container import Container, build_node_resolver, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes.base import NodeContext
from maistro.graph.nodes.llm_summarize import LlmSummarizeNode, LlmSummarizeOut
from maistro.runs.model import RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_SOURCE
from maistro.types.config import AgentConfig


async def _container(**overrides: object) -> Container:
    return await create_container(
        AgentConfig(router_api_key="test-key", **overrides)  # type: ignore[arg-type]
    )


async def test_configured_model_bindings_bootstrap_into_container_effect_context() -> None:
    container = await _container(
        workspace_id="ws-default",
        model_bindings=[
            {
                "binding_id": "model-default-workspace",
                "project_id": "project-a",
                "provider_name": "model-a",
            },
            {
                "binding_id": "model-explicit-workspace",
                "workspace_id": "ws-explicit",
                "project_id": "project-b",
                "provider_name": "model-b",
            },
        ],
    )

    inherited = await container.capability_effects.bindings.resolve(
        "model-default-workspace",
        workspace_id="ws-default",
        project_id="project-a",
        node_id="summarize",
        capability=MODEL_CHAT_CAPABILITY,
    )
    explicit = await container.capability_effects.bindings.resolve(
        "model-explicit-workspace",
        workspace_id="ws-explicit",
        project_id="project-b",
        node_id="summarize",
        capability=MODEL_CHAT_CAPABILITY,
    )

    assert inherited.workspace_id == "ws-default"
    assert inherited.provider_name == "model-a"
    assert explicit.workspace_id == "ws-explicit"
    assert explicit.provider_name == "model-b"


async def test_empty_model_binding_config_authorizes_nothing() -> None:
    container = await _container(workspace_id="ws-default")

    with pytest.raises(BindingNotFound):
        await container.capability_effects.bindings.resolve(
            "not-configured",
            workspace_id="ws-default",
            project_id="project-a",
            node_id="summarize",
            capability=MODEL_CHAT_CAPABILITY,
        )


async def test_container_resolved_summarize_uses_real_authorities_and_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_config = tmp_path / "providers.yaml"
    provider_config.write_text(
        "models:\n"
        "  - name: yaml-model\n"
        "    provider: openai\n"
        "    cost_input: 1.0\n"
        "    cost_output: 2.0\n"
        "    latency_p50_ms: 300\n",
        encoding="utf-8",
    )
    container = await _container(
        workspace_id="ws-prod",
        provider_config_path=str(provider_config),
        model_bindings=[
            {
                "binding_id": "model-prod",
                "project_id": "project-prod",
                "provider_name": "yaml-model",
            },
            {
                "binding_id": "model-router",
                "project_id": "project-prod",
            },
        ],
    )
    resolver = build_node_resolver(
        effect_context=container.capability_effects,
        provider_registry=container.provider_registry,
        llm_router=container.llm_router,
    )
    node = resolver("summarize", {"nodes": [{"id": "summarize", "kind": "llm.summarize"}]})

    assert isinstance(node, LlmSummarizeNode)
    assert node._effects is container.capability_effects
    assert node._registry is container.provider_registry
    assert node._router is container.llm_router

    metadata = await node._registry.get_model("yaml-model")
    calls: list[str] = []

    async def fake_execute_model_chat(
        provider: Any, payload: Any, *, endpoint: Any
    ) -> dict[str, Any]:
        del payload
        calls.append(provider.name)
        assert provider.metadata is metadata
        assert endpoint.base_url == "https://gateway.test"
        return {
            "model": "yaml-model-2026-09",
            "choices": [{"message": {"content": "A governed summary."}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }

    import maistro.capabilities.model_chat as model_chat

    monkeypatch.setattr(model_chat, "execute_model_chat", fake_execute_model_chat)
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://gateway.test")

    result = await node.run(
        {
            "text": "Long source text",
            "model": "request-alias-that-binding-pin-outranks",
            "binding_id": "model-prod",
        },
        NodeContext(
            run_id="run-prod",
            dag_id="graph-prod",
            node_id="summarize",
            node_run_id="node-run-prod",
            attempt_id="attempt-prod",
            workspace_id="ws-prod",
            project_id="project-prod",
        ),
    )

    assert result.success is True
    assert isinstance(result.output, LlmSummarizeOut)
    assert result.output.summary == "A governed summary."
    assert calls == ["yaml-model"]

    invocations = await container.capability_effects.invocation_store.list_effect(
        run_id="run-prod",
        node_run_id="node-run-prod",
        binding_id="model-prod",
        effect_key="llm.summarize.complete:request-alias-that-binding-pin-outranks",
    )
    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.attempt_id == "attempt-prod"
    assert invocation.usage is not None
    assert invocation.usage.input_units == 1000
    assert invocation.usage.output_units == 500
    assert invocation.usage.cost_cents == 2.0
    assert invocation.usage.provider == "openai"
    assert invocation.usage.model == "yaml-model"
    assert invocation.usage.model_version == "yaml-model-2026-09"

    routed = await node.run(
        {
            "text": "Route through the Container's populated registry",
            "model": "",
            "binding_id": "model-router",
        },
        NodeContext(
            run_id="run-router",
            dag_id="graph-prod",
            node_id="summarize",
            node_run_id="node-run-router",
            attempt_id="attempt-router",
            workspace_id="ws-prod",
            project_id="project-prod",
        ),
    )
    assert routed.success is True
    assert calls == ["yaml-model", "yaml-model"]

    denied = await node.run(
        {
            "text": "Must not dispatch",
            "model": "request-alias-that-binding-pin-outranks",
            "binding_id": "model-prod",
        },
        NodeContext(
            run_id="run-denied",
            dag_id="graph-prod",
            node_id="summarize",
            node_run_id="node-run-denied",
            attempt_id="attempt-denied",
            workspace_id="ws-other",
            project_id="project-prod",
        ),
    )
    assert denied.success is False
    assert denied.error_code == "BindingScopeDenied"
    assert calls == ["yaml-model", "yaml-model"]


def _provider_yaml(tmp_path: Path) -> str:
    provider_config = tmp_path / "providers.yaml"
    provider_config.write_text(
        "models:\n"
        "  - name: yaml-model\n"
        "    provider: openai\n"
        "    cost_input: 1.0\n"
        "    cost_output: 2.0\n"
        "    latency_p50_ms: 300\n",
        encoding="utf-8",
    )
    return str(provider_config)


async def _admit_summarize_run(container: Container, project_id: str) -> Any:
    """Admit one single-node `llm.summarize` Run the schedule consumer owns."""
    graph = Graph(
        workspace_id="tick-ws",
        project_id=project_id,
        name="scheduled summarize",
        nodes=[
            Node(
                node_id="n1",
                node_type="llm.summarize",
                parameters={
                    "text": "Scheduled source text",
                    "model": "",
                    "binding_id": "model-tick",
                },
            )
        ],
    )
    return await container.run_store.create_run(
        graph,
        provenance={ADMISSION_SOURCE: SCHEDULE_SOURCE},
        initial_status=RunStatus.QUEUED,
    )


async def test_consumer_tick_executes_a_configured_summarize_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The strongest composition proof: the Container's own consumer tick.

    The node is built by `execute_admitted_runs`' internally wired resolver —
    not by a resolver the test assembled — and the Binding it resolves exists
    only because the deployment declared it and the production registration
    path (`bootstrap_model_bindings`, the same function `create_container`
    runs at startup) loaded it into the Container's one effect context. A
    canonical Project id is generated at runtime, so the declaration targets
    the real root — the same re-declaration a control plane performs when a
    Project comes to exist. Authorization is therefore removable: drop the
    registration (the twin test below) and the same Run fails closed before
    any dispatch. The transport is replaced only at the final physical seam.
    """
    import maistro.capabilities.model_chat as model_chat
    from maistro.capabilities.model_binding_bootstrap import bootstrap_model_bindings

    container = await _container(
        workspace_id="tick-ws",
        provider_config_path=_provider_yaml(tmp_path),
    )
    root = await container.project_scope_store.create_root("tick-ws")
    await bootstrap_model_bindings(
        AgentConfig(
            router_api_key="test-key",
            workspace_id="tick-ws",
            model_bindings=[{"binding_id": "model-tick", "project_id": root.project_id}],
        ),
        container.capability_effects,
    )
    admitted = await _admit_summarize_run(container, root.project_id)

    metadata = await container.provider_registry.get_model("yaml-model")
    calls: list[str] = []

    async def fake_execute_model_chat(
        provider: Any, payload: Any, *, endpoint: Any
    ) -> dict[str, Any]:
        del payload
        calls.append(provider.name)
        assert provider.metadata is metadata
        return {
            "model": "yaml-model-2026-09",
            "choices": [{"message": {"content": "A tick-driven summary."}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 250},
        }

    monkeypatch.setattr(model_chat, "execute_model_chat", fake_execute_model_chat)
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://gateway.test")

    assert await container.execute_admitted_runs() == 1

    record = await container.run_store.get_run(admitted.run_id)
    assert record is not None and record.status is RunStatus.COMPLETED
    assert calls == ["yaml-model"]

    # Unpinned selection went through the Container's own populated router,
    # and the Invocation carries registry-derived cost + Run correlation.
    node_runs = await container.run_store.list_node_runs(admitted.run_id)
    node_run_id = node_runs[0].node_run_id
    attempts = await container.run_store.list_attempts(node_run_id)
    invocations = await container.capability_effects.invocation_store.list_effect(
        run_id=admitted.run_id,
        node_run_id=node_run_id,
        binding_id="model-tick",
        effect_key="llm.summarize.complete:",
    )
    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.usage is not None
    assert invocation.usage.input_units == 500
    assert invocation.usage.output_units == 250
    # 0.5K input * 1.0 + 0.25K output * 2.0 = 1.0 cent of registry pricing.
    assert invocation.usage.cost_cents == 1.0
    assert invocation.usage.model == "yaml-model"
    assert invocation.attempt_id == attempts[0].attempt_id


async def test_consumer_tick_fails_closed_without_a_declared_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The twin: no registered authorization, no dispatch, no fabricated success.

    The same Run shape against a container where the registration step never
    ran must refuse the node before any physical call — removing the
    bootstrap path is what turns the previous test into this one, which is
    the removal-detection the acceptance asks for. A refused node parks the
    Run (a node failure is parked by the reconciler, never silently retried),
    so the honest assertions are the failed NodeRun, the refusal reason, and
    the empty Invocation ledger.
    """
    import maistro.capabilities.model_chat as model_chat

    container = await _container(
        workspace_id="tick-ws",
        provider_config_path=_provider_yaml(tmp_path),
    )
    root = await container.project_scope_store.create_root("tick-ws")
    admitted = await _admit_summarize_run(container, root.project_id)

    calls: list[str] = []

    async def fake_execute_model_chat(
        provider: Any, payload: Any, *, endpoint: Any
    ) -> dict[str, Any]:
        calls.append(provider.name)
        return {"choices": [{"message": {"content": "must not happen"}}]}

    monkeypatch.setattr(model_chat, "execute_model_chat", fake_execute_model_chat)
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://gateway.test")

    assert await container.execute_admitted_runs() == 1

    record = await container.run_store.get_run(admitted.run_id)
    assert record is not None and record.status is not RunStatus.COMPLETED
    node_runs = await container.run_store.list_node_runs(admitted.run_id)
    assert node_runs, "the tick must have recorded a NodeRun"
    assert "BindingNotFound" in str(node_runs[0].error)
    assert calls == []
    invocations = await container.capability_effects.invocation_store.list_effect(
        run_id=admitted.run_id,
        node_run_id=node_runs[0].node_run_id,
        binding_id="model-tick",
        effect_key="llm.summarize.complete:",
    )
    assert invocations == []


async def test_synth_dag_child_resolver_carries_the_container_authorities() -> None:
    """The synth catalog offers `llm.summarize`, so the parent's child resolver
    must carry the Container wiring down (#1079).

    `agent.synth_dag` used to fall through to bare registry construction in
    every production resolver, so a synthesized child graph built its
    `llm.summarize` against a fresh empty effect context, registry and router
    no matter what the deployment had configured or what the parent was
    wired with."""
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode

    container = await _container()
    resolver = build_node_resolver(
        effect_context=container.capability_effects,
        provider_registry=container.provider_registry,
        llm_router=container.llm_router,
    )

    parent = resolver("s", {"nodes": [{"id": "s", "kind": "agent.synth_dag"}]})
    assert isinstance(parent, AgentSynthDagNode)
    assert parent._node_resolver is not None
    assert parent._run_store is None  # bare resolver: no store to inherit

    child = parent._node_resolver("n1", {"nodes": [{"id": "n1", "kind": "llm.summarize"}]})
    assert isinstance(child, LlmSummarizeNode)
    assert child._effects is container.capability_effects
    assert child._registry is container.provider_registry
    assert child._router is container.llm_router


async def test_container_resolved_summarize_uses_the_configured_gateway_not_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`AgentConfig.litellm_url`/`litellm_key` reach the wired node (#1079 review).

    The node used to read only the environment, so a Container configured
    programmatically held a valid endpoint its own nodes could not see.
    """
    for name in (
        "MAISTRO_LLM_BASE_URL",
        "LITELLM_URL",
        "LITELLM_API_BASE",
        "MAISTRO_LLM_API_KEY",
        "LITELLM_API_KEY",
        "LITELLM_MASTER_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    container = await _container(
        workspace_id="ws-cfg",
        litellm_url="https://configured.gateway.test",
        litellm_key="configured-key",
        model_bindings=[{"binding_id": "model-cfg", "project_id": "project-cfg"}],
    )
    resolver = build_node_resolver(
        effect_context=container.capability_effects,
        provider_registry=container.provider_registry,
        llm_router=container.llm_router,
        gateway_endpoint=container.gateway_endpoint,
    )
    node = resolver("summarize", {"nodes": [{"id": "summarize", "kind": "llm.summarize"}]})
    assert isinstance(node, LlmSummarizeNode)
    assert node._endpoint is container.gateway_endpoint
    seen: list[Any] = []

    async def fake_execute_model_chat(
        provider: Any, payload: Any, *, endpoint: Any
    ) -> dict[str, Any]:
        del payload
        seen.append((provider.name, endpoint))
        return {
            "model": "gw-alias",
            "choices": [{"message": {"content": "A configured summary."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    import maistro.capabilities.model_chat as model_chat

    monkeypatch.setattr(model_chat, "execute_model_chat", fake_execute_model_chat)

    result = await node.run(
        {"text": "Long source text", "model": "gw-alias", "binding_id": "model-cfg"},
        NodeContext(
            run_id="run-cfg",
            dag_id="graph-cfg",
            node_id="summarize",
            node_run_id="node-run-cfg",
            attempt_id="attempt-cfg",
            workspace_id="ws-cfg",
            project_id="project-cfg",
        ),
    )

    assert result.status == "completed", result.error_message
    ((model, endpoint),) = seen
    # No registry metadata: the gateway alias passed through as the model.
    assert model == "gw-alias"
    assert endpoint.base_url == "https://configured.gateway.test"
    assert endpoint.api_key == "configured-key"
    await container.aclose()


async def test_sqlite_container_keeps_the_invocation_ledger_across_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A durable backend gets a durable ledger (#1079 review): after a restart
    the same Invocation row is found, so recovery can deduplicate rather than
    charge the same logical model call twice."""
    import httpx

    from maistro.capabilities.binding import Binding
    from maistro.capabilities.invocation import InvocationStatus
    from maistro.capabilities.invocation_store import SqliteInvocationStore
    from maistro.capabilities.model_chat import ModelChatEgress, ModelChatRequest
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro.events.envelope import SqliteEventStore

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {
                "model": "gw-alias",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    database_url = f"sqlite:///{tmp_path / 'ledger.db'}"
    container = await _container(workspace_id="ws-ledger", database_url=database_url)
    try:
        assert isinstance(container.capability_effects.invocation_store, SqliteInvocationStore)
        assert isinstance(container.capability_effects.event_store, SqliteEventStore)
        binding = await container.capability_effects.bindings.put(
            Binding(
                binding_id="model-ledger",
                workspace_id="ws-ledger",
                project_id="project-ledger",
                capability=MODEL_CHAT_CAPABILITY,
            )
        )
        egress = ModelChatEgress(
            container.capability_effects,
            registry=container.provider_registry,
            router=container.llm_router,
            endpoint=GatewayEndpoint(base_url="http://gw"),
        )
        result = await egress.complete(
            binding=binding,
            run_id="run-ledger",
            node_run_id="node-run-ledger",
            attempt_id="attempt-ledger",
            effect_key="llm.summarize.complete:gw-alias",
            request=ModelChatRequest(
                model="gw-alias", messages=[{"role": "user", "content": "hi"}]
            ),
        )
    finally:
        await container.aclose()

    reopened = await _container(workspace_id="ws-ledger", database_url=database_url)
    try:
        durable = await reopened.capability_effects.invocation_store.get(result.invocation_id)
        assert durable is not None
        assert durable.status is InvocationStatus.COMPLETED
        assert durable.effect_key == "llm.summarize.complete:gw-alias"
    finally:
        await reopened.aclose()
