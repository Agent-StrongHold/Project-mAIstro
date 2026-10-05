"""Conductor admission, retry and circuit proofs with only HTTP substituted."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, replace
from datetime import timedelta

import httpx
import pytest

from maistro.agents.circuit_breaker import CircuitOpenError, CircuitState, DomainCircuitBank
from maistro.agents.conductor import ConductorCall, _run_with_retry, conductor_failure_domain
from maistro.agents.types import LLMProviderError
from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.capabilities.model_binding_bootstrap import bootstrap_model_bindings
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint, LlmHttpError
from maistro.config.models import DEFAULT_TIERS, Tier
from maistro.graph.definitions import Graph, Node
from maistro.http import set_test_transport
from maistro.observability.correlation import bind_execution_context
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.types.config import AgentConfig, ModelBindingConfig

CALL = ConductorCall(
    model="primary", base_url="http://gateway.fixture", api_key="unused", system_prompt="system"
)
TIER = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 2, "timeout": 23})


@pytest.fixture(autouse=True)
def isolated_transport(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def no_delay(_seconds: float) -> None:
        return None

    monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", no_delay)
    yield
    set_test_transport(None)


@dataclass
class AdmittedConductor:
    calls: AdmittedModelCalls
    effects: CapabilityEffectContext
    runs: InMemoryRunStore
    identity: tuple[str, str, str]
    project_id: str
    sent: list[httpx.Request]
    router: CostAwareRouter

    async def invocation(self, number: int) -> Invocation:
        records = await self.effects.invocation_store.list_effect(
            run_id=self.identity[0],
            node_run_id=self.identity[1],
            binding_id="conductor-configured",
            effect_key=f"conductor-llm-{number}",
        )
        assert len(records) == 1
        return records[0]


def answer() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "provider-version",
            "choices": [{"message": {"content": '{"success": true, "final_answer": "done"}'}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5},
        },
    )


async def setup_conductor(
    handler: Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]] = lambda _: (
        answer()
    ),
    *,
    configured: bool = True,
    pin: str = "",
) -> AdmittedConductor:
    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("conductor-workspace")
    runs = InMemoryRunStore(project_store=projects)
    graph = Graph(
        name="conductor-admission",
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        nodes=[Node(node_id="task", node_type="chat", name="task")],
    )
    run = await runs.create_run(
        graph, actor_principal_id="authenticated-actor", initial_status=RunStatus.QUEUED
    )
    await runs.transition_run(run.run_id, RunStatus.RUNNING)
    node = await runs.create_node_run(run.run_id, node_id="task")
    for step in transition_path(node.status, RunStatus.RUNNING):
        node = await runs.transition_node_run(node.node_run_id, step)
    attempt = await runs.create_attempt(
        node.node_run_id, lease_holder="conductor-fixture", lease_ttl=timedelta(minutes=5)
    )
    assert attempt.execution_lease is not None
    await runs.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    effects = new_in_memory_effect_context(
        policy_evaluator=binding_scope_policy, usage_log=InMemoryUsageLog()
    )
    config = AgentConfig(
        workspace_id=project.workspace_id,
        litellm_key="binding-key",
        model_bindings=[
            ModelBindingConfig(
                binding_id="conductor-configured",
                project_id=project.project_id,
                provider_name=pin,
            )
        ]
        if configured
        else [],
    )
    await bootstrap_model_bindings(config, effects)
    registry = InMemoryProviderRegistry(
        [
            ModelMetadata(
                name=name,
                provider=name,
                fallback_to=("secondary",) if name == "primary" else (),
                cost_per_1k_input=0,
                cost_per_1k_output=0,
                latency_p50_ms=1,
            )
            for name in ("primary", "secondary")
        ]
    )
    router = CostAwareRouter(registry)
    sent: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response | Awaitable[httpx.Response]:
        sent.append(request)
        return handler(request)

    set_test_transport(httpx.MockTransport(capture))
    calls = AdmittedModelCalls(
        effects,
        registry=registry,
        router=router,
        endpoint=GatewayEndpoint(base_url=CALL.base_url or "", api_key="never-use-this-key"),
        run_store=runs,
        binding_ids=tuple(binding.binding_id for binding in config.model_bindings),
    )
    return AdmittedConductor(
        calls,
        effects,
        runs,
        (run.run_id, node.node_run_id, attempt.attempt_id),
        project.project_id,
        sent,
        router,
    )


async def test_conductor_uses_persisted_context_actor_binding_and_usage() -> None:
    setup = await setup_conductor()
    with bind_execution_context(
        run_id=setup.identity[0], node_run_id=setup.identity[1], attempt_id=setup.identity[2]
    ):
        result = await _run_with_retry(
            CALL,
            "task prompt",
            TIER,
            512,
            admitted_calls=setup.calls,
            circuits=DomainCircuitBank(),
        )
    invocation = await setup.invocation(0)
    assert result.final_answer == "done"
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.actor_id == "authenticated-actor"
    assert invocation.binding.binding_id == "conductor-configured"
    assert invocation.binding.project_id == setup.project_id
    assert (invocation.run_id, invocation.node_run_id, invocation.attempt_id) == setup.identity
    assert len(setup.sent) == 1
    request = setup.sent[0]
    assert request.url == "http://gateway.fixture/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer binding-key"
    assert request.extensions["timeout"] == {
        "connect": 23,
        "read": 23,
        "write": 23,
        "pool": 23,
    }
    payload = json.loads(request.content)
    assert payload["max_tokens"] == 512
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"][-1] == {"role": "user", "content": "task prompt"}
    events = setup.effects.usage_log.events_for("primary")
    assert len(events) == 1
    assert events[0].invocation_id == invocation.invocation_id
    assert events[0].input_tokens == 11
    assert events[0].output_tokens == 5


@pytest.mark.parametrize("identity", [None, ("invented-run", "invented-node", "invented-attempt")])
async def test_conductor_missing_or_invented_context_has_zero_http(
    identity: tuple[str, str, str] | None,
) -> None:
    setup = await setup_conductor()
    with pytest.raises(RunIntegrityError):
        await _run_with_retry(
            CALL,
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=identity,
            circuits=DomainCircuitBank(),
        )
    assert setup.sent == []


@pytest.mark.parametrize("configured", [False, True])
async def test_conductor_unconfigured_or_revoked_binding_has_zero_http(configured: bool) -> None:
    setup = await setup_conductor(configured=configured)
    if configured:
        await setup.effects.bindings.revoke("conductor-configured")
    with pytest.raises(BindingResolutionError):
        await _run_with_retry(
            CALL,
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=DomainCircuitBank(),
        )
    assert setup.sent == []


@pytest.mark.parametrize("failure", ["connect", "connect_timeout", "json"])
async def test_canonical_failures_retry_as_distinct_invocations(failure: str) -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count > 1:
            return answer()
        if failure == "connect":
            raise httpx.ConnectError("fixture connection refused", request=request)
        if failure == "connect_timeout":
            raise httpx.ConnectTimeout("fixture connection timeout", request=request)
        if failure == "json":
            return httpx.Response(200, json={"choices": [{"message": {"content": "invalid"}}]})
        return httpx.Response(503)

    setup = await setup_conductor(handler)
    result = await _run_with_retry(
        CALL,
        "task",
        TIER,
        128,
        admitted_calls=setup.calls,
        invocation_identity=setup.identity,
        circuits=DomainCircuitBank(),
    )
    first, second = await setup.invocation(0), await setup.invocation(1)
    assert result.success is True
    assert len(setup.sent) == 2
    assert first.invocation_id != second.invocation_id
    assert first.attempt_id == second.attempt_id == setup.identity[2]
    assert first.binding.binding_id == second.binding.binding_id == "conductor-configured"
    assert (
        first.status
        is {
            "connect": InvocationStatus.FAILED,
            "connect_timeout": InvocationStatus.FAILED,
            "json": InvocationStatus.COMPLETED,
        }[failure]
    )
    assert second.status is InvocationStatus.COMPLETED


@pytest.mark.parametrize("status", [400, 429, 502, 503, 504])
async def test_canonical_http_refusal_does_not_retry(status: int) -> None:
    setup = await setup_conductor(lambda _request: httpx.Response(status))
    with pytest.raises(LlmHttpError, match=f"status={status}"):
        await _run_with_retry(
            CALL,
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=DomainCircuitBank(),
        )
    assert len(setup.sent) == 1
    assert (await setup.invocation(0)).status is InvocationStatus.UNKNOWN


async def test_canonical_connect_failure_opens_only_shared_gateway_breaker() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fixture gateway unavailable", request=request)

    setup = await setup_conductor(refuse)
    circuits = DomainCircuitBank(failure_threshold=2)
    domain = conductor_failure_domain(CALL)
    with pytest.raises(LLMProviderError, match="failed after 2 retries"):
        await _run_with_retry(
            CALL,
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=circuits,
        )
    assert circuits.breaker(domain).state is CircuitState.CLOSED
    assert not circuits.admit(domain)
    with pytest.raises(CircuitOpenError):
        await _run_with_retry(
            CALL,
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=circuits,
            router=setup.router,
        )
    assert len(setup.sent) == 2


async def test_outer_timeout_keeps_unknown_invocation_without_redispatch() -> None:
    async def never_answers(_request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    setup = await setup_conductor(never_answers)
    circuits = DomainCircuitBank(failure_threshold=1)
    with pytest.raises(TimeoutError):
        await _run_with_retry(
            CALL,
            "task",
            TIER.model_copy(update={"timeout": 1}),
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=circuits,
        )
    assert len(setup.sent) == 1
    assert (await setup.invocation(0)).status is InvocationStatus.UNKNOWN
    assert circuits.breaker(conductor_failure_domain(CALL)).state is CircuitState.OPEN


async def test_provider_json_decode_failure_is_unknown_and_does_not_retry() -> None:
    setup = await setup_conductor(lambda _request: httpx.Response(200, content=b"invalid-json"))
    with pytest.raises(json.JSONDecodeError):
        await _run_with_retry(
            CALL,
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=DomainCircuitBank(),
        )
    assert len(setup.sent) == 1
    assert (await setup.invocation(0)).status is InvocationStatus.UNKNOWN


async def test_open_pinned_provider_cannot_escape_through_router_fallback() -> None:
    setup = await setup_conductor(pin="primary")
    circuits = DomainCircuitBank(failure_threshold=1)
    circuits.record_failure(conductor_failure_domain(CALL))
    with pytest.raises(CircuitOpenError):
        await _run_with_retry(
            CALL,
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=circuits,
            router=setup.router,
        )
    assert setup.sent == []


async def test_circuit_records_actual_binding_pin_instead_of_requested_alias() -> None:
    setup = await setup_conductor(lambda _request: httpx.Response(503), pin="secondary")
    circuits = DomainCircuitBank(failure_threshold=1)
    with pytest.raises(LlmHttpError):
        await _run_with_retry(
            CALL,
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=circuits,
            router=setup.router,
        )
    actual = conductor_failure_domain(replace(CALL, model="secondary"))
    assert circuits.breaker(actual).state is CircuitState.OPEN
    assert circuits.breaker(conductor_failure_domain(CALL)).state is CircuitState.CLOSED
    assert len(setup.sent) == 1
    assert json.loads(setup.sent[0].content)["model"] == "secondary"


async def test_circuit_uses_canonical_endpoint_instead_of_legacy_call_url() -> None:
    setup = await setup_conductor()
    circuits = DomainCircuitBank(failure_threshold=1)
    circuits.record_failure(conductor_failure_domain(CALL), shared=True)
    with pytest.raises(CircuitOpenError):
        await _run_with_retry(
            replace(CALL, base_url="http://legacy.fixture"),
            "task",
            TIER,
            128,
            admitted_calls=setup.calls,
            invocation_identity=setup.identity,
            circuits=circuits,
            router=setup.router,
        )
    assert setup.sent == []


async def test_declared_router_fallback_keeps_configured_binding_and_actor() -> None:
    setup = await setup_conductor()
    circuits = DomainCircuitBank(failure_threshold=1)
    circuits.record_failure(conductor_failure_domain(CALL))
    result = await _run_with_retry(
        CALL,
        "task",
        TIER,
        128,
        admitted_calls=setup.calls,
        invocation_identity=setup.identity,
        circuits=circuits,
        router=setup.router,
    )
    invocation = await setup.invocation(0)
    assert result.success is True
    assert json.loads(setup.sent[0].content)["model"] == "secondary"
    assert invocation.binding.binding_id == "conductor-configured"
    assert invocation.binding.provider_name == "secondary"
    assert invocation.actor_id == "authenticated-actor"


async def test_missing_composition_refuses_before_circuit_admission() -> None:
    bank = DomainCircuitBank(failure_threshold=1)
    with pytest.raises(LLMProviderError, match="admitted model-call authority"):
        await _run_with_retry(CALL, "prompt", TIER, 32, circuits=bank)
    assert bank.admit(conductor_failure_domain(CALL))
