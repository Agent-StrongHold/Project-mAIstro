"""Production-composition proof for governed model egress (#1079)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
from maistro.container import Container, build_node_resolver, create_container
from maistro.graph.nodes.base import NodeContext
from maistro.graph.nodes.llm_summarize import LlmSummarizeNode
from maistro.types.config import AgentConfig


async def _container(**overrides: object) -> Container:
    return await create_container(AgentConfig(router_api_key="test-key", **overrides))  # type: ignore[arg-type]


async def test_configured_model_bindings_bootstrap_into_the_container_effect_context() -> None:
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


async def test_container_resolved_summarize_uses_real_authorities_and_governed_invocation(
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
            }
        ],
    )
    resolver = build_node_resolver(
        effect_context=container.capability_effects,
        provider_registry=container.provider_registry,
        llm_router=container.llm_router,
    )
    graph = {"nodes": [{"id": "summarize", "kind": "llm.summarize"}]}
    node = resolver("summarize", graph)

    assert isinstance(node, LlmSummarizeNode)
    assert node._effects is container.capability_effects
    assert node._registry is container.provider_registry
    assert node._router is container.llm_router

    metadata = await node._registry.get_model("yaml-model")
    assert metadata.provider == "openai"
    assert metadata.cost_per_1k_input == 1.0
    assert metadata.cost_per_1k_output == 2.0

    calls: list[str] = []

    async def fake_execute_model_chat(provider: Any, payload: Any, *, endpoint: Any) -> dict[str, Any]:
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
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "test-secret")

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
    assert getattr(result.output, "summary") == "A governed summary."
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
    assert calls == ["yaml-model"]
