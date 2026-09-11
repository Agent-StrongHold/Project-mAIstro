from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.providers import llm_gateway
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.policy.types import Decision, PolicyVerdict
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata


def _runtime():
    from services.governed_model import GovernedModelRuntime

    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="judge-model",
                provider="test-provider",
                cost_per_1k_input=0.5,
                cost_per_1k_output=1.0,
                latency_p50_ms=100,
            )
        ]
    )
    return GovernedModelRuntime(
        effects=new_in_memory_effect_context(),
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gateway", api_key="master"),
    )


class _Response:
    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


@pytest.fixture
def fake_gateway(monkeypatch: pytest.MonkeyPatch):
    body = {
        "model": "judge-model-v2",
        "choices": [{"message": {"content": '{"total": 42, "pass": true}'}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> _Response:
            calls.append((url, kwargs.get("json", {})))
            return _Response(body)

    @asynccontextmanager
    async def _shared_client(*args: Any, **kwargs: Any):
        del args, kwargs
        yield _Client()

    monkeypatch.setattr(llm_gateway, "shared_client", _shared_client)
    return calls


@pytest.mark.asyncio
async def test_benchmark_evaluation_records_correlated_invocation(
    monkeypatch: pytest.MonkeyPatch, fake_gateway: list[tuple[str, dict[str, Any]]]
) -> None:
    import services.benchmark_eval as benchmark_eval

    runtime = _runtime()
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: runtime)

    score = await benchmark_eval.evaluate_code_output(
        "implement add",
        "plan",
        "def add(a, b): return a + b",
        run_id="run-1",
        node_run_id="benchmark-node-1",
        attempt_id="benchmark-attempt-1",
        workspace_id="ws-1",
        project_id="project-1",
        model="judge-model",
    )

    assert score["total"] == 42
    assert score["invocation_id"]
    stored = await runtime.effects.invocation_store.get(score["invocation_id"])
    assert stored is not None
    assert stored.run_id == "run-1"
    assert stored.node_run_id == "benchmark-node-1"
    assert stored.attempt_id == "benchmark-attempt-1"
    assert stored.usage is not None
    assert stored.usage.model == "judge-model"
    assert "response_format" in fake_gateway[0][1]


@pytest.mark.asyncio
async def test_provider_health_registration_keeps_secret_out_of_invocation(
    fake_gateway: list[tuple[str, dict[str, Any]]],
) -> None:
    from services.governed_model import (
        control_plane_binding,
        register_and_health_check,
        resolve_binding,
    )

    runtime = _runtime()
    binding = control_plane_binding(
        binding_id="provider-binding",
        workspace_id="ws-1",
        project_id="provider-project",
        provider_name="judge-model",
    )
    await runtime.effects.bindings.put(binding)
    binding = await resolve_binding(runtime, binding)

    result = await register_and_health_check(
        runtime=runtime,
        binding=binding,
        run_id="activation-run",
        node_run_id="health-node",
        attempt_id="health-attempt",
        provider_name="judge-model",
        models=("judge-model",),
        api_key="provider-secret",
    )

    assert result.model == "judge-model"
    stored = await runtime.effects.invocation_store.get(result.invocation_id)
    assert stored is not None
    assert stored.request is not None
    assert "provider-secret" not in repr(stored.request)
    assert fake_gateway[0][0].endswith("/model/new")
    assert fake_gateway[0][1]["litellm_params"]["api_key"] == "provider-secret"
    assert fake_gateway[1][0].endswith("/chat/completions")


@pytest.mark.asyncio
async def test_provider_health_policy_denial_is_not_reported_as_provider_failure(
    fake_gateway: list[tuple[str, dict[str, Any]]],
) -> None:
    from services.governed_model import (
        GovernedModelRuntime,
        ProviderAuthorizationError,
        control_plane_binding,
        register_and_health_check,
        resolve_binding,
    )

    async def deny(*args: Any, **kwargs: Any) -> PolicyVerdict:
        del args, kwargs
        return PolicyVerdict(Decision.DENY, reason="operator binding denied", rule="test-deny")

    base_runtime = _runtime()
    runtime = GovernedModelRuntime(
        effects=new_in_memory_effect_context(policy_evaluator=deny),
        registry=base_runtime.registry,
        router=base_runtime.router,
        endpoint=GatewayEndpoint(base_url="http://gateway", api_key="master"),
    )
    binding = control_plane_binding(
        binding_id="denied-provider-binding",
        workspace_id="ws-1",
        project_id="provider-project",
        provider_name="judge-model",
    )
    await runtime.effects.bindings.put(binding)
    binding = await resolve_binding(runtime, binding)

    with pytest.raises(ProviderAuthorizationError, match="authorization"):
        await register_and_health_check(
            runtime=runtime,
            binding=binding,
            run_id="activation-run-denied",
            node_run_id="health-node-denied",
            attempt_id="health-attempt-denied",
            provider_name="judge-model",
            models=("judge-model",),
            api_key="provider-secret",
        )
    assert fake_gateway[0][0].endswith("/model/new")
    assert len(fake_gateway) == 1


async def test_evaluation_without_canonical_scope_is_truthful() -> None:
    from services.benchmark_eval import evaluate_code_output

    result = await evaluate_code_output("task", "plan", "code")

    assert result["error_kind"] == "authorization"
    assert result["pass"] is False
