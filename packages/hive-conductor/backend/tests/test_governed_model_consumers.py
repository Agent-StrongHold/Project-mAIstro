from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.providers import llm_gateway
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.graph.definitions import Graph, Node
from maistro.policy.types import Decision, PolicyVerdict
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore


async def _canonical_scope(workspace_id: str = "ws-1") -> tuple[InMemoryProjectScopeStore, str]:
    scope = InMemoryProjectScopeStore()
    root = await scope.create_root(workspace_id)
    return scope, root.project_id


async def _admit_parent_run(
    run_store: InMemoryRunStore, *, workspace_id: str, project_id: str
) -> str:
    """Admit the completed canonical Run whose output the evaluator will judge."""

    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="evaluated-dag",
        nodes=[Node(node_id="worker", node_type="worker", name="worker")],
    )
    run = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    await run_store.transition_run(run.run_id, RunStatus.RUNNING)
    await run_store.transition_run(run.run_id, RunStatus.COMPLETED)
    return run.run_id


async def _correlated_runtime(
    policy_evaluator: Any = None,
) -> tuple[Any, Any, str, str]:
    """A GovernedModelRuntime whose run store sits on a real canonical spine."""

    from hive_conductor.services.governed_model import GovernedModelRuntime

    scope, project_id = await _canonical_scope()
    run_store = InMemoryRunStore(project_store=scope)
    parent_run_id = await _admit_parent_run(run_store, workspace_id="ws-1", project_id=project_id)
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
    runtime = GovernedModelRuntime(
        effects=new_in_memory_effect_context(policy_evaluator=policy_evaluator),
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gateway", api_key="master"),
        project_scope_store=scope,
        run_store=run_store,
    )
    return runtime, run_store, parent_run_id, project_id


def _plain_runtime():
    from hive_conductor.services.governed_model import GovernedModelRuntime

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
    def __init__(self, body: dict[str, Any], status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code

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

    runtime, run_store, parent_run_id, project_id = await _correlated_runtime()
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: runtime)

    score = await benchmark_eval.evaluate_code_output(
        "implement add",
        "plan",
        "def add(a, b): return a + b",
        run_id=parent_run_id,
        workspace_id="ws-1",
        project_id=project_id,
        model="judge-model",
    )

    assert score["total"] == 42
    assert score["invocation_id"]

    # The Invocation correlates to real canonical records, not invented ids.
    stored = await runtime.effects.invocation_store.get(score["invocation_id"])
    assert stored is not None
    operation_run = await run_store.get_run(stored.run_id)
    assert operation_run is not None
    assert operation_run.parent_run_id == parent_run_id
    assert operation_run.provenance["evaluated_run_id"] == parent_run_id
    node_run = await run_store.get_node_run(stored.node_run_id)
    assert node_run is not None
    assert node_run.run_id == stored.run_id
    attempt = await run_store.get_attempt(stored.attempt_id)
    assert attempt is not None
    assert attempt.node_run_id == stored.node_run_id

    # The operation terminalized truthfully: the evaluation completed.
    assert operation_run.status is RunStatus.COMPLETED
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.accepted_outcome is not None
    assert node_run.accepted_outcome.attempt_result.attempt_id == attempt.attempt_id
    assert attempt.status is AttemptStatus.COMPLETED

    assert stored.usage is not None
    assert stored.usage.model == "judge-model"
    assert "response_format" in fake_gateway[0][1]


@pytest.mark.asyncio
async def test_benchmark_evaluation_without_canonical_run_is_refused(
    monkeypatch: pytest.MonkeyPatch, fake_gateway: list[tuple[str, dict[str, Any]]]
) -> None:
    """An unknown Run cannot be evaluated: there is nothing to correlate to."""

    import services.benchmark_eval as benchmark_eval

    runtime, _run_store, _parent_run_id, project_id = await _correlated_runtime()
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: runtime)

    result = await benchmark_eval.evaluate_code_output(
        "task",
        "plan",
        "code",
        run_id="no-such-canonical-run",
        workspace_id="ws-1",
        project_id=project_id,
    )

    assert result["error_kind"] == "authorization"
    assert result["pass"] is False
    # No model HTTP happened and no Invocation was minted against fiction.
    assert fake_gateway == []
    assert (
        await runtime.effects.invocation_store.list_effect(
            run_id="no-such-canonical-run",
            node_run_id="benchmark-evaluation",
            binding_id="benchmark-evaluation:no-such-canonical-run",
            effect_key="benchmark.evaluation:judge",
        )
        == []
    )


@pytest.mark.asyncio
async def test_evaluation_without_canonical_scope_is_truthful() -> None:
    from hive_conductor.services.benchmark_eval import evaluate_code_output

    result = await evaluate_code_output("task", "plan", "code")

    assert result["error_kind"] == "authorization"
    assert result["pass"] is False


@pytest.mark.asyncio
async def test_provider_health_registration_keeps_secret_out_of_invocation(
    fake_gateway: list[tuple[str, dict[str, Any]]],
) -> None:
    from hive_conductor.services.governed_model import (
        control_plane_binding,
        register_and_health_check,
        resolve_binding,
    )

    runtime = _plain_runtime()
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
async def test_provider_health_policy_denial_causes_zero_http(
    monkeypatch: pytest.MonkeyPatch, fake_gateway: list[tuple[str, dict[str, Any]]]
) -> None:
    """A denied policy must not register provider models first (#1088).

    The credential-bearing /model/new registration is Invocation-internal
    setup: authorization refusal means zero gateway requests, and the minted
    operation records report cancelled, not failed.
    """

    from hive_conductor.services.governed_model import (
        GovernedModelRuntime,
        ProviderAuthorizationError,
        control_plane_binding,
        register_and_health_check,
        resolve_binding,
    )

    async def deny(*args: Any, **kwargs: Any) -> PolicyVerdict:
        del args, kwargs
        return PolicyVerdict(Decision.DENY, reason="operator binding denied", rule="test-deny")

    base_runtime = _plain_runtime()
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
    assert fake_gateway == []
    assert (
        await runtime.effects.invocation_store.list_effect(
            run_id="activation-run-denied",
            node_run_id="health-node-denied",
            binding_id="denied-provider-binding",
            effect_key="provider.health:judge-model",
        )
        == []
    )


@pytest.mark.asyncio
async def test_provider_health_with_minted_identity_completes_operation(
    fake_gateway: list[tuple[str, dict[str, Any]]],
) -> None:
    """Full activation flow on a canonical spine: minted identity -> health
    invocation -> settled completed operation. This mirrors what the route
    does, runnable without the vault backend."""

    from hive_conductor.services.governed_model import (
        control_plane_binding,
        ensure_binding,
        mint_operation_identity,
        register_and_health_check,
        resolve_binding,
        settle_operation_identity,
    )

    runtime, run_store, _parent_run_id, project_id = await _correlated_runtime()
    binding = control_plane_binding(
        binding_id="provider-activation:judge",
        workspace_id="ws-1",
        project_id=project_id,
        provider_name="judge-model",
    )
    binding = await ensure_binding(runtime, binding)
    binding = await resolve_binding(runtime, binding)
    identity = await mint_operation_identity(
        runtime,
        operation="provider-activation:judge",
        workspace_id="ws-1",
        project_id=project_id,
        provenance={"activation_source": "routes.providers", "provider": "judge"},
    )

    result = await register_and_health_check(
        runtime=runtime,
        binding=binding,
        run_id=identity.run_id,
        node_run_id=identity.node_run_id,
        attempt_id=identity.attempt_id,
        provider_name="judge-model",
        models=("judge-model",),
        api_key="provider-secret",
    )
    await settle_operation_identity(
        runtime,
        identity,
        outcome="completed",
        result={"invocation_id": result.invocation_id, "model": result.model},
    )

    stored = await runtime.effects.invocation_store.get(result.invocation_id)
    assert stored is not None
    assert stored.run_id == identity.run_id
    operation = await run_store.get_run(identity.run_id)
    assert operation is not None
    assert operation.status.value == "completed"
    assert operation.provenance["operation"] == "provider-activation:judge"
    node_run = await run_store.get_node_run(identity.node_run_id)
    assert node_run is not None and node_run.accepted_outcome is not None
    attempt = await run_store.get_attempt(identity.attempt_id)
    assert attempt is not None and attempt.status.value == "completed"
    # Registration ran inside the Invocation (post-authorization), then health.
    assert fake_gateway[0][0].endswith("/model/new")
    assert fake_gateway[1][0].endswith("/chat/completions")


@pytest.mark.asyncio
async def test_provider_registration_failure_is_not_authorization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway that refuses registration is an activation failure, reported
    distinctly from policy denial, with the Invocation recording UNKNOWN."""

    from hive_conductor.services.governed_model import (
        ProviderActivationError,
        control_plane_binding,
        register_and_health_check,
        resolve_binding,
    )

    calls: list[tuple[str, dict[str, Any]]] = []

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> _Response:
            calls.append((url, kwargs.get("json", {})))
            if url.endswith("/model/new"):
                return _Response({}, status_code=500)
            return _Response(
                {
                    "model": "judge-model",
                    "choices": [{"message": {"content": "pong"}}],
                }
            )

    @asynccontextmanager
    async def _shared_client(*args: Any, **kwargs: Any):
        del args, kwargs
        yield _Client()

    monkeypatch.setattr(llm_gateway, "shared_client", _shared_client)

    runtime = _plain_runtime()
    binding = control_plane_binding(
        binding_id="registration-failure-binding",
        workspace_id="ws-1",
        project_id="provider-project",
        provider_name="judge-model",
    )
    await runtime.effects.bindings.put(binding)
    binding = await resolve_binding(runtime, binding)

    with pytest.raises(ProviderActivationError, match="HTTP 500"):
        await register_and_health_check(
            runtime=runtime,
            binding=binding,
            run_id="activation-run-regfail",
            node_run_id="health-node-regfail",
            attempt_id="health-attempt-regfail",
            provider_name="judge-model",
            models=("judge-model",),
            api_key="provider-secret",
        )

    assert [url for url, _ in calls] == ["http://gateway/model/new"]
    stored = await runtime.effects.invocation_store.get(
        (
            await runtime.effects.invocation_store.list_effect(
                run_id="activation-run-regfail",
                node_run_id="health-node-regfail",
                binding_id="registration-failure-binding",
                effect_key="provider.health:judge-model",
            )
        )[0].invocation_id
    )
    assert stored is not None
    assert stored.status is InvocationStatus.UNKNOWN


@pytest.mark.asyncio
async def test_ensure_binding_is_immutable_and_idempotent() -> None:
    """Bindings register once: an identical re-registration returns the stored
    record; a mutated one is refused as an authorization failure."""
    from hive_conductor.services.governed_model import control_plane_binding, ensure_binding

    from maistro.capabilities.binding_store import BindingResolutionError

    runtime, _run_store, _parent_run_id, project_id = await _correlated_runtime()
    binding = control_plane_binding(
        binding_id="immutable-binding",
        workspace_id="ws-1",
        project_id=project_id,
        provider_name="judge-model",
    )

    stored = await ensure_binding(runtime, binding)
    assert stored == binding
    again = await ensure_binding(runtime, binding)
    assert again == stored

    mutated = binding.model_copy(update={"provider_name": "other-model"})
    with pytest.raises(BindingResolutionError, match="immutable"):
        await ensure_binding(runtime, mutated)


@pytest.mark.asyncio
async def test_runtime_fails_closed_without_container() -> None:
    """The hive bridge refuses model egress when no core Container is bound —
    degraded mode never fabricates a runtime."""
    from hive_conductor.services.governed_model import _runtime

    with pytest.raises(RuntimeError, match="canonical model egress is unavailable"):
        _runtime()


@pytest.mark.asyncio
async def test_runtime_wires_container_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_runtime`` builds the governed runtime from the live container's
    authorities and the gateway endpoint from the environment chain."""
    from types import SimpleNamespace

    import services.engine as engine_mod
    from hive_conductor.services.governed_model import _runtime

    engine = engine_mod.get_engine()
    scope, _project_id = await _canonical_scope()
    run_store = InMemoryRunStore(project_store=scope)
    registry = InMemoryProviderRegistry()
    effects = new_in_memory_effect_context()
    router = CostAwareRouter(registry)
    container = SimpleNamespace(
        capability_effects=effects,
        provider_registry=registry,
        llm_router=router,
        project_scope_store=scope,
        run_store=run_store,
    )
    monkeypatch.setattr(engine, "_agent_port", SimpleNamespace(container=container))
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://env-gateway")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "env-key")

    runtime = _runtime()

    assert runtime.effects is effects
    assert runtime.registry is registry
    assert runtime.router is router
    assert runtime.project_scope_store is scope
    assert runtime.run_store is run_store
    assert runtime.endpoint.base_url == "http://env-gateway"
    assert runtime.endpoint.api_key == "env-key"


@pytest.mark.asyncio
async def test_endpoint_refuses_without_gateway_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env endpoint and no configured settings is a fail-closed 503-class
    error, never an implicit default endpoint."""
    import hive_conductor.config as config
    from hive_conductor.services.governed_model import ProviderActivationError, _endpoint

    for var in (
        "MAISTRO_LLM_BASE_URL",
        "LITELLM_PROXY_URL",
        "LITELLM_API_BASE",
        "MAISTRO_LLM_API_KEY",
        "LITELLM_API_KEY",
        "LITELLM_PROXY_KEY",
        "LITELLM_MASTER_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = type("Settings", (), {"litellm_api_base": None, "litellm_api_key": None})()
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    with pytest.raises(ProviderActivationError, match="LLM gateway is not configured"):
        _endpoint()


@pytest.mark.asyncio
async def test_mint_refuses_without_canonical_run_store() -> None:
    """Minting an operation without the canonical run store fails closed."""
    import services.governed_model as governed_model

    runtime = _plain_runtime()
    with pytest.raises(RuntimeError, match="without the core Container run store"):
        await governed_model.mint_operation_identity(
            runtime,
            operation="orphan-operation",
            workspace_id="ws-1",
            project_id="p-1",
        )


@pytest.mark.asyncio
async def test_settle_rejects_unknown_outcome() -> None:
    """Only completed/failed/cancelled are legal operation outcomes."""
    import services.governed_model as governed_model

    runtime, _run_store, parent_run_id, project_id = await _correlated_runtime()
    identity = await governed_model.mint_operation_identity(
        runtime,
        operation="settle-check",
        workspace_id="ws-1",
        project_id=project_id,
        parent_run_id=parent_run_id,
    )
    with pytest.raises(ValueError, match="unknown operation outcome"):
        await governed_model.settle_operation_identity(runtime, identity, outcome="bogus")


@pytest.mark.asyncio
async def test_settle_records_failed_and_cancelled_operations() -> None:
    """Failed and cancelled operations terminalize their canonical spine
    truthfully (Run/NodeRun/Attempt), keeping authorization refusals
    distinguishable from execution failures."""
    import services.governed_model as governed_model

    runtime, run_store, parent_run_id, project_id = await _correlated_runtime()
    failed = await governed_model.mint_operation_identity(
        runtime,
        operation="op-failed",
        workspace_id="ws-1",
        project_id=project_id,
        parent_run_id=parent_run_id,
    )
    cancelled = await governed_model.mint_operation_identity(
        runtime,
        operation="op-cancelled",
        workspace_id="ws-1",
        project_id=project_id,
        parent_run_id=parent_run_id,
    )

    await governed_model.settle_operation_identity(
        runtime, failed, outcome="failed", error="gateway exploded"
    )
    await governed_model.settle_operation_identity(
        runtime, cancelled, outcome="cancelled", error="authorization refused"
    )

    failed_run = await run_store.get_run(failed.run_id)
    cancelled_run = await run_store.get_run(cancelled.run_id)
    assert failed_run is not None and failed_run.status is RunStatus.FAILED
    assert failed_run.error == "gateway exploded"
    assert cancelled_run is not None and cancelled_run.status is RunStatus.CANCELLED
    failed_node = await run_store.get_node_run(failed.node_run_id)
    assert failed_node is not None and failed_node.status is RunStatus.FAILED
    cancelled_node = await run_store.get_node_run(cancelled.node_run_id)
    assert cancelled_node is not None and cancelled_node.status is RunStatus.CANCELLED
    failed_attempt = await run_store.get_attempt(failed.attempt_id)
    assert failed_attempt is not None and failed_attempt.status is AttemptStatus.FAILED
    cancelled_attempt = await run_store.get_attempt(cancelled.attempt_id)
    assert cancelled_attempt is not None and cancelled_attempt.status is AttemptStatus.CANCELLED


@pytest.mark.asyncio
async def test_benchmark_authorization_denial_settles_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A policy-deny on the judge call returns an authorization error kind and
    settles the evaluation operation as CANCELLED."""
    import services.benchmark_eval as benchmark_eval

    async def deny(*args: Any, **kwargs: Any) -> PolicyVerdict:
        del args, kwargs
        return PolicyVerdict(Decision.DENY, reason="benchmark denied", rule="test-deny")

    runtime, run_store, parent_run_id, project_id = await _correlated_runtime(policy_evaluator=deny)
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: runtime)

    score = await benchmark_eval.evaluate_code_output(
        "task",
        "plan",
        "code",
        run_id=parent_run_id,
        workspace_id="ws-1",
        project_id=project_id,
        model="judge-model",
    )

    assert score["error_kind"] == "authorization"
    assert score["pass"] is False
    cancelled = await run_store.list_by_status(RunStatus.CANCELLED, limit=10)
    children = [
        run for run in cancelled if run.provenance.get("operation") == "benchmark-evaluation"
    ]
    assert len(children) == 1


@pytest.mark.asyncio
async def test_benchmark_transport_failure_settles_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable gateway is an evaluation failure (not authorization):
    the error kind is ``evaluation`` and the operation settles FAILED."""
    from contextlib import asynccontextmanager

    import httpx
    import services.benchmark_eval as benchmark_eval

    runtime, run_store, parent_run_id, project_id = await _correlated_runtime()
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: runtime)

    class _DeadClient:
        async def __aenter__(self) -> _DeadClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            del args

        async def post(self, url: str, **kwargs: Any) -> Any:
            del url, kwargs
            raise httpx.ConnectError("gateway unreachable")

    @asynccontextmanager
    async def _dead_shared_client(*args: Any, **kwargs: Any):
        del args, kwargs
        yield _DeadClient()

    monkeypatch.setattr(llm_gateway, "shared_client", _dead_shared_client)

    score = await benchmark_eval.evaluate_code_output(
        "task",
        "plan",
        "code",
        run_id=parent_run_id,
        workspace_id="ws-1",
        project_id=project_id,
        model="judge-model",
    )

    assert score["error_kind"] == "evaluation"
    assert score["total"] == 0
    failed = await run_store.list_by_status(RunStatus.FAILED, limit=10)
    children = [run for run in failed if run.provenance.get("operation") == "benchmark-evaluation"]
    assert len(children) == 1


@pytest.mark.asyncio
async def test_evaluate_dag_run_joins_aggregated_outputs(
    monkeypatch: pytest.MonkeyPatch, fake_gateway: list[tuple[str, dict[str, Any]]]
) -> None:
    """DAG-run evaluation judges the joined plan/code/review decomposition of
    every successful node output, positionally."""
    import services.benchmark_eval as benchmark_eval

    from maistro.providers.types import ModelMetadata

    runtime, _run_store, parent_run_id, project_id = await _correlated_runtime()
    runtime.registry.register_model(
        ModelMetadata(
            name="gemini-3.5-flash",
            provider="test-provider",
            cost_per_1k_input=0.5,
            cost_per_1k_output=1.0,
            latency_p50_ms=100,
        )
    )
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: runtime)

    result = {
        "run_id": parent_run_id,
        "workspace_id": "ws-1",
        "project_id": project_id,
        "node_results": {
            "planner": {"response": "the-plan-text", "success": True},
            "worker-1": {"response": "the-code-part-1", "success": True},
            "worker-2": {"response": "the-code-part-2", "success": True},
            "reviewer": {"response": "the-review-text", "success": True},
            "skipped": {"response": "should-not-appear", "success": False},
        },
    }

    score = await benchmark_eval.evaluate_dag_run(result, "build the thing")

    assert score["total"] == 42
    assert score["evaluation_run_id"]
    user_message = fake_gateway[0][1]["messages"][-1]["content"]
    assert "TASK:\nbuild the thing" in user_message
    assert "PLAN:\nthe-plan-text" in user_message
    assert "the-code-part-1\nthe-code-part-2" in user_message
    assert "REVIEW:\nthe-review-text" in user_message
    assert "should-not-appear" not in user_message
