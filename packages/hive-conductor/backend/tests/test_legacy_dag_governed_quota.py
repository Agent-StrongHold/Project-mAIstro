"""Admitted Workspace DAG model calls reach the canonical quota ledger (#718).

A real Container supplies configured Bindings, credentials and the canonical Run
spine. Only the final HTTP transport is substituted. Missing authority fails
closed even when a caller supplies a legacy builder or enables raw stubs.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from services.dag_execution_scope import DagExecutionScope

from maistro.http import override_transport
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.types import ModelMetadata
from maistro.types.config import AgentConfig, ModelBindingConfig

_NODE_MODEL = "test-dag-model"


def _dag() -> dict[str, Any]:
    return {
        "id": "governed-quota-dag",
        "name": "governed-quota-dag",
        "description": "one governed model call",
        "nodes": [
            {
                "id": "n1",
                "role": "worker",
                "name": "n1",
                "prompt": "do governed work",
                "model": _NODE_MODEL,
                "config": {"execution_tier": "safe"},
            }
        ],
        "edges": [],
        "entry_node": "n1",
    }


class _GatewayTransport:
    """Final TEST transport; request construction and authority remain real."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        return httpx.Response(200, json=self.body)


def _model_registry() -> InMemoryProviderRegistry:
    """An explicit Binding pin requires trusted, registered model metadata."""
    return InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name=_NODE_MODEL,
                provider="test-provider",
                cost_per_1k_input=0.5,
                cost_per_1k_output=1.0,
                latency_p50_ms=100,
            )
        ]
    )


class _RecordingTracker:
    """Spy on exactly what the canonical recorder charged the tracker."""

    def __init__(self) -> None:
        self.invocations: list[dict[str, Any]] = []

    async def record_invocation(
        self,
        invocation_id: str,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
        usage_reported: bool,
    ) -> dict[str, Any]:
        self.invocations.append(
            {
                "invocation_id": invocation_id,
                "provider": provider,
                "billing_cycle": billing_cycle,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "usage_reported": usage_reported,
            }
        )
        return {"provider": provider}


def _gateway_body(*, usage: dict[str, int] | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": _NODE_MODEL,
        "choices": [{"message": {"role": "assistant", "content": '{"done": true}'}}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


@asynccontextmanager
async def _install_container(
    monkeypatch: pytest.MonkeyPatch, tracker: _RecordingTracker
) -> AsyncIterator[tuple[Any, Any, Any, DagExecutionScope]]:
    """Provision explicit test authority after the Container allocates its Project."""
    import services.canonical_dag_runner as runner

    from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
    from maistro.capabilities.model_binding_bootstrap import bootstrap_model_bindings
    from maistro.container import create_container
    from maistro.providers.router import CostAwareRouter
    from maistro.quota.usage_log import InMemoryUsageLog

    usage_log = InMemoryUsageLog()
    effects = new_effect_context(
        usage_log=usage_log,
        quota_tracker=tracker,
        policy_evaluator=binding_scope_policy,
    )
    config = AgentConfig(
        router_api_key="test-router-key",
        database_url="memory://",
        workspace_id="ws-quota",
        litellm_url="http://gateway.test",
        litellm_key="test-gateway-key",
    )
    container = await create_container(config, effect_context=effects)
    try:
        project = await container.project_scope_store.create_root(config.workspace_id)
        config.model_bindings.append(
            ModelBindingConfig(
                binding_id="quota-dag-model",
                project_id=project.project_id,
                node_id="n1",
                provider_name=_NODE_MODEL,
            )
        )
        await bootstrap_model_bindings(config, effects)
        container.provider_registry = _model_registry()
        container.llm_router = CostAwareRouter(container.provider_registry)
        monkeypatch.setattr(runner, "_container", lambda: container)
        monkeypatch.setattr(runner, "get_run_store", lambda: container.graph_run_store)
        scope = DagExecutionScope(
            workspace_id=config.workspace_id, project_id=project.project_id, user_id="quota-user"
        )
        yield container, usage_log, effects.invocation_store, scope
    finally:
        await container.aclose()


@pytest.mark.asyncio
async def test_dag_node_model_call_records_invocation_quota_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One admitted completion records quota once with its canonical identity."""
    from services.canonical_dag_runner import execute_dag

    tracker = _RecordingTracker()
    transport = _GatewayTransport(
        _gateway_body(usage={"prompt_tokens": 13, "completion_tokens": 7})
    )
    async with _install_container(monkeypatch, tracker) as (
        container,
        usage_log,
        invocations,
        scope,
    ):
        with override_transport(httpx.MockTransport(transport)):
            result = await execute_dag(_dag(), scope=scope)

        assert result["status"] == "completed", result
        node = result["node_results"]["n1"]
        assert node["success"] is True
        assert node["response"] == '{"done": true}'

        assert len(transport.seen) == 1
        served = transport.seen[0]
        assert str(served.url) == "http://gateway.test/v1/chat/completions"
        assert json.loads(served.content)["model"] == _NODE_MODEL
        assert served.headers["Authorization"] == "Bearer test-gateway-key"

        assert usage_log.scope_keys() == (_NODE_MODEL,)
        (event,) = usage_log.events_for(_NODE_MODEL)
        assert event.usage_reported is True
        assert event.input_tokens == 13
        assert event.output_tokens == 7
        assert event.invocation_id
        invocation = await invocations.get(event.invocation_id)
        assert invocation is not None
        assert invocation.actor_id == scope.user_id
        assert invocation.binding.binding_id == "quota-dag-model"
        assert invocation.run_id == result["run_id"]
        assert await container.run_store.get_attempt(invocation.attempt_id) is not None

        assert len(tracker.invocations) == 1
        charge = tracker.invocations[0]
        assert charge["provider"] == _NODE_MODEL
        assert charge["usage_reported"] is True
        assert (charge["input_tokens"], charge["output_tokens"]) == (13, 7)
        assert charge["invocation_id"] == event.invocation_id


@pytest.mark.asyncio
async def test_dag_node_without_provider_usage_records_unreported_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing provider usage remains unreported, never an apparently free call."""
    from services.canonical_dag_runner import execute_dag

    tracker = _RecordingTracker()
    transport = _GatewayTransport(_gateway_body(usage=None))
    async with _install_container(monkeypatch, tracker) as (_container, usage_log, _store, scope):
        with override_transport(httpx.MockTransport(transport)):
            result = await execute_dag(_dag(), scope=scope)

        assert result["status"] == "completed", result
        assert len(transport.seen) == 1
        (event,) = usage_log.events_for(_NODE_MODEL)
        assert event.usage_reported is False
        assert (event.input_tokens, event.output_tokens) == (0, 0)
        assert len(tracker.invocations) == 1
        charge = tracker.invocations[0]
        assert charge["usage_reported"] is False
        assert charge["invocation_id"] == event.invocation_id


def test_dag_node_model_calls_refuses_partial_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every collaborator and a Container-configured endpoint are required."""
    from services.governed_model import dag_node_model_calls

    from maistro.capabilities.admitted_model import AdmittedModelCalls

    assert dag_node_model_calls(None) is None
    collaborators = {
        "capability_effects": SimpleNamespace(),
        "provider_registry": _model_registry(),
        "llm_router": SimpleNamespace(),
        "run_store": SimpleNamespace(),
        "config": AgentConfig(litellm_url="http://configured.test"),
    }
    for missing in collaborators:
        partial = {key: value for key, value in collaborators.items() if key != missing}
        assert dag_node_model_calls(SimpleNamespace(**partial)) is None

    # Ambient deployment values cannot fill a missing Container endpoint or key.
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://ambient.test")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "ambient-key")
    empty_endpoint = {**collaborators, "config": AgentConfig(litellm_url="")}
    assert dag_node_model_calls(SimpleNamespace(**empty_endpoint)) is None

    runtime = dag_node_model_calls(SimpleNamespace(**collaborators))
    assert isinstance(runtime, AdmittedModelCalls)
    assert runtime.gateway_base_url == "http://configured.test"
    assert not runtime._endpoint.api_key
    assert runtime._effects is collaborators["capability_effects"]


@pytest.mark.asyncio
async def test_dag_node_without_effect_authority_fails_closed_without_raw_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw builders, response hooks and stub opt-in cannot authorize dispatch."""
    import services.canonical_dag_runner as runner

    calls: list[str] = []

    def _fake_builder(on_response: Any = None):
        calls.append("builder")

        async def call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            calls.append("completion")
            return "ok:legacy"

        return call

    def on_response(*_args: Any) -> None:
        calls.append("response hook")

    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setenv("ALLOW_STUB_LLM", "true")
    transport = _GatewayTransport(_gateway_body(usage=None))
    with override_transport(httpx.MockTransport(transport)):
        result = await runner.execute_dag(
            _dag(),
            scope=DagExecutionScope(
                workspace_id="ws-quota", project_id="proj-quota", user_id="quota-user"
            ),
            llm_builder=_fake_builder,
            on_response=on_response,
        )

    assert result["status"] == "failed", result
    assert result["node_results"]["n1"]["success"] is False
    assert "admitted model runtime and context" in result["node_results"]["n1"]["response"]
    assert calls == []
    assert transport.seen == []
