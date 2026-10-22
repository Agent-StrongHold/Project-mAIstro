from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import pytest

from maistro.capabilities.effect_context import (
    binding_scope_policy,
    new_in_memory_effect_context,
)
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
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


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
    run = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    await run_store.transition_run(run.run_id, RunStatus.RUNNING)
    await run_store.transition_run(run.run_id, RunStatus.COMPLETED)
    return run.run_id


async def _correlated_runtime(
    policy_evaluator: Any = binding_scope_policy,
) -> tuple[Any, Any, str, str]:
    """A GovernedModelRuntime whose run store sits on a real canonical spine.

    Defaults to the explicit M1 baseline policy (#846): an omitted evaluator is
    an unavailable dependency and denies, so behavior tests must opt in and
    denial tests pass their denying evaluator explicitly.
    """

    from services.governed_model import GovernedModelRuntime

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


async def _benchmark_runtime(runtime: Any, project_id: str) -> Any:
    """An operator-configured evaluator grant, not a consumer-issued one."""
    from services.benchmark_eval import BenchmarkRuntime

    from maistro.capabilities.admitted_model import AdmittedModelCalls
    from maistro.capabilities.model_binding_bootstrap import bootstrap_model_bindings
    from maistro.types.config import AgentConfig, ModelBindingConfig

    config = AgentConfig(
        workspace_id="ws-1",
        litellm_key="configured-test-key",
        model_bindings=[
            ModelBindingConfig(
                binding_id="configured-evaluator",
                project_id=project_id,
                node_id="benchmark-evaluation",
            )
        ],
    )
    await bootstrap_model_bindings(config, runtime.effects)
    return BenchmarkRuntime(
        runs=runtime.run_store,
        calls=AdmittedModelCalls(
            runtime.effects,
            registry=runtime.registry,
            router=runtime.router,
            endpoint=GatewayEndpoint(base_url="http://gateway"),
            run_store=runtime.run_store,
            binding_ids=("configured-evaluator",),
        ),
    )


def _plain_runtime():
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
        # Behavior fixture: explicit M1 baseline policy (#846 — omitted policy
        # evaluators now deny, they never default to permissive).
        effects=new_in_memory_effect_context(policy_evaluator=binding_scope_policy),
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
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            **{
                                name: {
                                    "score": 8.4,
                                    "evidence": "specific evidence",
                                    "fix": "specific fix",
                                }
                                for name in (
                                    "correctness",
                                    "completeness",
                                    "test_coverage",
                                    "style",
                                    "security",
                                )
                            },
                            "total": 42,
                            "pass": True,
                            "summary": "review summary",
                            "suggested_prompt_improvement": "better prompt",
                        }
                    )
                }
            }
        ],
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
    evaluator = await _benchmark_runtime(runtime, project_id)
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: evaluator)

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
    evaluator = await _benchmark_runtime(runtime, project_id)
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: evaluator)

    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError):
        await benchmark_eval.evaluate_code_output(
            "task",
            "plan",
            "code",
            run_id="no-such-canonical-run",
            workspace_id="ws-1",
            project_id=project_id,
        )

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
    from services.benchmark_eval import BenchmarkAuthorizationError, evaluate_code_output

    with pytest.raises(BenchmarkAuthorizationError):
        await evaluate_code_output("task", "plan", "code")


async def _activate_provider_fixture(runtime: Any, binding: Any) -> Any:
    from services.provider_activation import activate

    class Vault:
        def use(self, name: str, callback: Any) -> Any:
            return callback("provider-secret")

    return await activate(
        runtime=runtime,
        binding=binding,
        actor_principal_id="test-admin",
        name="judge",
        provider_name="judge-model",
        models=("judge-model",),
        vault=Vault(),
        secret_name="fixture-key",
    )


async def _provider_fixture(policy: Any = binding_scope_policy) -> tuple[Any, Any]:
    from services.governed_model import control_plane_binding, ensure_binding

    runtime, _runs, _parent, project_id = await _correlated_runtime(policy)
    binding = control_plane_binding(
        runtime,
        binding_id="provider-activation:judge",
        workspace_id="ws-1",
        project_id=project_id,
        provider_name="judge-model",
    )
    return runtime, await ensure_binding(runtime, binding)


@pytest.mark.asyncio
async def test_provider_health_registration_keeps_secret_out_of_invocation(
    fake_gateway: list[tuple[str, dict[str, Any]]],
) -> None:
    runtime, binding = await _provider_fixture()
    result = await _activate_provider_fixture(runtime, binding)
    assert result.model == "judge-model"
    stored = await runtime.effects.invocation_store.get(result.invocation_id)
    assert stored is not None and stored.request is not None
    assert "provider-secret" not in stored.model_dump_json()
    assert fake_gateway[0][0].endswith("/model/new")
    assert fake_gateway[0][1]["litellm_params"]["api_key"] == "provider-secret"
    assert fake_gateway[1][0].endswith("/chat/completions")


@pytest.mark.asyncio
async def test_provider_health_policy_denial_causes_zero_http(
    fake_gateway: list[tuple[str, dict[str, Any]]],
) -> None:
    from services.governed_model import ProviderAuthorizationError

    async def deny(*args: Any, **kwargs: Any) -> PolicyVerdict:
        return PolicyVerdict(Decision.DENY, reason="operator binding denied", rule="test-deny")

    runtime, binding = await _provider_fixture(deny)
    with pytest.raises(ProviderAuthorizationError, match="authorization"):
        await _activate_provider_fixture(runtime, binding)
    assert fake_gateway == []
    (operation,) = await runtime.run_store.list_by_status(RunStatus.CANCELLED)
    (node,) = await runtime.run_store.list_node_runs(operation.run_id)
    assert (
        await runtime.effects.invocation_store.list_effect(
            run_id=operation.run_id,
            node_run_id=node.node_run_id,
            binding_id=binding.binding_id,
            effect_key="provider.health:judge-model",
        )
        == []
    )


@pytest.mark.asyncio
async def test_provider_health_with_admitted_execution_completes_operation(
    fake_gateway: list[tuple[str, dict[str, Any]]],
) -> None:
    """Canonical service owns the real leased Attempt and accepted logical outcome."""
    runtime, binding = await _provider_fixture()
    result = await _activate_provider_fixture(runtime, binding)
    stored = await runtime.effects.invocation_store.get(result.invocation_id)
    assert stored is not None
    operation = await runtime.run_store.get_run(stored.run_id)
    assert operation.status is RunStatus.COMPLETED
    assert operation.provenance["operation"] == "provider-activation:judge"
    node = await runtime.run_store.get_node_run(stored.node_run_id)
    assert node.accepted_outcome is not None
    attempt = await runtime.run_store.get_attempt(stored.attempt_id)
    assert attempt.status is AttemptStatus.COMPLETED
    assert attempt.execution_lease is not None
    assert fake_gateway[0][0].endswith("/model/new")
    assert fake_gateway[1][0].endswith("/chat/completions")


@pytest.mark.asyncio
async def test_provider_registration_failure_is_not_authorization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.governed_model import ProviderActivationError

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

    runtime, binding = await _provider_fixture()
    with pytest.raises(ProviderActivationError, match="registration failed"):
        await _activate_provider_fixture(runtime, binding)
    assert [url for url, _ in calls] == ["http://gateway/model/new"]
    (operation,) = await runtime.run_store.list_by_status(RunStatus.FAILED)
    (node,) = await runtime.run_store.list_node_runs(operation.run_id)
    (stored,) = await runtime.effects.invocation_store.list_effect(
        run_id=operation.run_id,
        node_run_id=node.node_run_id,
        binding_id=binding.binding_id,
        effect_key="provider.health:judge-model",
    )
    assert stored.status is InvocationStatus.UNKNOWN


@pytest.mark.asyncio
async def test_ensure_binding_is_immutable_and_idempotent() -> None:
    """Bindings register once: an identical re-registration returns the stored
    record; a mutated one is refused as an authorization failure."""
    from services.governed_model import control_plane_binding, ensure_binding

    from maistro.capabilities.binding_store import BindingResolutionError

    runtime, _run_store, _parent_run_id, project_id = await _correlated_runtime()
    binding = control_plane_binding(
        runtime,
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
async def test_control_plane_binding_reregistration_preserves_credential_cooldown() -> None:
    """#1079 Finding 2: consecutive control-plane calls reusing the same
    Workspace/Project (e.g. repeated benchmark evaluations or provider
    activations) must not reset a credential's tracked cooldown/blocked
    state -- `control_plane_binding` re-registers the runtime's gateway
    credential on every call, and that re-registration must not undo the
    outcome-driven backoff `record_outcome` already recorded for it."""

    from services.governed_model import control_plane_binding

    runtime = _plain_runtime()

    # First control-plane call: registers the credential and authorizes it.
    control_plane_binding(
        runtime,
        binding_id="benchmark-evaluation:run-1",
        workspace_id="ws-1",
        project_id="provider-project",
        provider_name="judge-model",
    )

    from maistro.capabilities.providers.llm_gateway import (
        DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
        MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    )

    class _UnauthorizedError(Exception):
        """A real HTTP-401-shaped error, the same status the credentials
        classifier reads off `status_code`/`response.status_code`."""

        def __init__(self) -> None:
            super().__init__("401 Unauthorized")
            self.status_code = 401
            self.response = type("Resp", (), {"status_code": 401, "headers": {}})

    # A real provider outcome (401) blocks that credential -- e.g. the
    # gateway key was rotated out from under this deployment.
    await runtime.effects.credentials.record_outcome(
        workspace_id="ws-1",
        project_id="provider-project",
        provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
        key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
        error=_UnauthorizedError(),
    )
    pool = runtime.effects.credentials.pool_for(
        workspace_id="ws-1",
        project_id="provider-project",
        provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    )
    assert pool is not None
    blocked_entry = next(
        e for e in pool._entries if e.key_id == DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF
    )
    assert blocked_entry.blocked is True

    # A second, unrelated control-plane call reuses the same Workspace/Project
    # (same scope `control_plane_binding` registers the credential into).
    control_plane_binding(
        runtime,
        binding_id="benchmark-evaluation:run-2",
        workspace_id="ws-1",
        project_id="provider-project",
        provider_name="judge-model",
    )

    still_blocked_entry = next(
        e for e in pool._entries if e.key_id == DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF
    )
    assert still_blocked_entry.blocked is True, (
        "re-registering the gateway credential must not clear the cooldown/"
        "block state an earlier 401 already set for it"
    )


@pytest.mark.asyncio
async def test_runtime_fails_closed_without_container() -> None:
    """The hive bridge refuses model egress when no core Container is bound —
    degraded mode never fabricates a runtime."""
    from services.governed_model import _runtime

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
    from services.governed_model import _runtime

    engine = engine_mod.get_engine()
    scope, _project_id = await _canonical_scope()
    run_store = InMemoryRunStore(project_store=scope)
    registry = InMemoryProviderRegistry()
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
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
    import config
    from services.governed_model import ProviderActivationError, _endpoint

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
async def test_benchmark_authorization_denial_settles_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A policy-deny on the judge call raises an authorization error and
    settles the evaluation operation as FAILED."""
    import services.benchmark_eval as benchmark_eval

    async def deny(*args: Any, **kwargs: Any) -> PolicyVerdict:
        del args, kwargs
        return PolicyVerdict(Decision.DENY, reason="benchmark denied", rule="test-deny")

    runtime, run_store, parent_run_id, project_id = await _correlated_runtime(policy_evaluator=deny)
    evaluator = await _benchmark_runtime(runtime, project_id)
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: evaluator)

    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError):
        await benchmark_eval.evaluate_code_output(
            "task",
            "plan",
            "code",
            run_id=parent_run_id,
            workspace_id="ws-1",
            project_id=project_id,
            model="judge-model",
        )

    cancelled = await run_store.list_by_status(RunStatus.FAILED, limit=10)
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
    evaluator = await _benchmark_runtime(runtime, project_id)
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: evaluator)

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

    with pytest.raises(benchmark_eval.BenchmarkEvaluationError):
        await benchmark_eval.evaluate_code_output(
            "task",
            "plan",
            "code",
            run_id=parent_run_id,
            workspace_id="ws-1",
            project_id=project_id,
            model="judge-model",
        )

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
    evaluator = await _benchmark_runtime(runtime, project_id)
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: evaluator)

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
