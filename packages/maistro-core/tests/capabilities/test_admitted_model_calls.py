"""Admission composes real execution, SDK routing and effect evidence.

Only HTTP is substituted. A timeout is expired after MockTransport dispatch,
so cancellation assertions do not depend on the machine reaching HTTP within
a small wall-clock interval or mistake a pre-dispatch refusal for an effect.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from maistro.capabilities import admitted_model
from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.governed_invocation import InvocationDenied
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    EffectNotApplied,
    Invocation,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.provider_adapters import (
    ProviderAdapterCatalog,
    ProviderAdapterSpec,
    ReferenceChatAdapter,
    configure_default_adapter_catalog,
    register_adapter_models,
    release_default_adapter_catalog,
)
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_CHAT_CAPABILITY,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    GatewayEndpoint,
    ModelChatRequest,
)
from maistro.credentials.router import CredentialScopeError
from maistro.credentials.types import CredentialRecord
from maistro.graph.definitions import Graph, Node
from maistro.http import set_test_transport
from maistro.observability.correlation import bind_execution_context
from maistro.policy.types import Decision, PolicyVerdict
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError

_RESPONSE = {
    "model": "provider-version-1",
    "choices": [{"message": {"role": "assistant", "content": "answer"}}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
}


async def _catalog(
    *, base_url: str = "https://owner.fixture/api", timeout_s: float = 11.0
) -> tuple[ProviderAdapterCatalog, InMemoryProviderRegistry]:
    spec = ProviderAdapterSpec.model_validate(
        {
            "adapter_id": "acme.models",
            "display_name": "Hermetic SDK fixture",
            "base_url": base_url,
            "credential_provider": "acme",
            "credential_ref": "acme-primary",
            "timeout_s": timeout_s,
            "capabilities": {"tools": True, "structured_output": True},
            "models": (
                {
                    "name": "acme-fast",
                    "cost_per_1k_input": 0.1,
                    "cost_per_1k_output": 0.2,
                    "latency_p50_ms": 10,
                    "tier": "fast",
                },
                {
                    "name": "acme-precise",
                    "cost_per_1k_input": 1.0,
                    "cost_per_1k_output": 2.0,
                    "latency_p50_ms": 100,
                    "tier": "powerful",
                    "capabilities": {"tools": True, "structured_output": True},
                },
            ),
        }
    )
    catalog = ProviderAdapterCatalog()
    registry = InMemoryProviderRegistry()
    await register_adapter_models(catalog, registry, ReferenceChatAdapter(spec))
    return catalog, registry


@dataclass
class _Harness:
    effects: CapabilityEffectContext
    runs: InMemoryRunStore
    registry: InMemoryProviderRegistry
    catalog: ProviderAdapterCatalog
    binding: Binding
    identity: tuple[str, str, str]
    fencing_token: str | None
    sent: list[httpx.Request]

    def consumer(
        self,
        *,
        adapters: ProviderAdapterCatalog | None = None,
        omit_catalog: bool = False,
        binding_ids: tuple[str, ...] | None = None,
        endpoint: GatewayEndpoint | None = None,
    ) -> AdmittedModelCalls:
        optional: dict[str, Any] = {}
        if not omit_catalog:
            optional["adapters"] = adapters if adapters is not None else self.catalog
        return AdmittedModelCalls(
            self.effects,
            registry=self.registry,
            router=CostAwareRouter(self.registry),
            endpoint=endpoint
            or GatewayEndpoint(
                base_url="https://gateway.fixture",
                api_key="unscoped-endpoint-key-must-not-be-used",
                timeout_s=120.0,
            ),
            run_store=self.runs,
            binding_ids=(self.binding.binding_id,) if binding_ids is None else binding_ids,
            **optional,
        )

    async def history(self) -> list[Invocation]:
        return await self.effects.invocation_store.list_effect(
            run_id=self.identity[0],
            node_run_id=self.identity[1],
            binding_id=self.binding.binding_id,
            effect_key="answer",
        )

    async def next_attempt(self) -> tuple[str, str, str]:
        await self.runs.transition_attempt(
            self.identity[2],
            AttemptStatus.CANCELLED,
            fencing_token=self.fencing_token,
        )
        attempt = await self.runs.create_attempt(
            self.identity[1], lease_holder="retry-worker", lease_ttl=timedelta(hours=1)
        )
        assert attempt.execution_lease is not None
        await self.runs.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token=attempt.execution_lease.fencing_token,
        )
        return self.identity[0], self.identity[1], attempt.attempt_id


async def _setup(
    *,
    sdk: bool = True,
    provider_name: str = "acme-precise",
    deadline_at: datetime | None = None,
    leased: bool = True,
    credentials: bool = True,
    disabled: bool = False,
) -> _Harness:
    scope = InMemoryProjectScopeStore()
    project = await scope.create_root("workspace")
    runs = InMemoryRunStore(project_store=scope)
    run = await runs.create_run(
        Graph(
            name="bounded-model-call",
            workspace_id="workspace",
            project_id=project.project_id,
            nodes=[Node(node_id="chat", node_type="chat", name="Chat")],
        ),
        actor_principal_id="canonical-actor",
        initial_status=RunStatus.QUEUED,
    )
    await runs.transition_run(run.run_id, RunStatus.RUNNING)
    node = await runs.create_node_run(run.run_id, node_id="chat")
    for step in transition_path(node.status, RunStatus.RUNNING):
        node = await runs.transition_node_run(node.node_run_id, step)
    attempt = await runs.create_attempt(
        node.node_run_id,
        lease_holder="fixture-worker" if leased else None,
        lease_ttl=timedelta(hours=1),
        deadline_at=deadline_at,
    )
    token = attempt.execution_lease.fencing_token if attempt.execution_lease else None
    await runs.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token)
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    catalog, registry = (
        await _catalog()
        if sdk
        else (
            ProviderAdapterCatalog(),
            InMemoryProviderRegistry(),
        )
    )
    key_id = "acme-primary" if sdk else DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF
    binding = Binding(
        binding_id="operator-declared",
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        node_id="chat",
        capability=MODEL_CHAT_CAPABILITY,
        provider_name=provider_name if sdk else "",
        disabled=disabled,
        config={"adapter_id": "acme.models"} if sdk else {},
        credential_refs=(key_id,),
    )
    await effects.bindings.put(binding)
    if credentials:
        effects.credentials.add(
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            record=CredentialRecord(
                key_id=key_id,
                provider="acme" if sdk else MODEL_GATEWAY_CREDENTIAL_PROVIDER,
                api_key="scoped-fixture-key",
            ),
        )
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=_RESPONSE)

    set_test_transport(httpx.MockTransport(respond))
    return _Harness(
        effects,
        runs,
        registry,
        catalog,
        binding,
        (run.run_id, node.node_run_id, attempt.attempt_id),
        token,
        sent,
    )


def _request(*, model: str = "acme-fast", structured: bool = False) -> ModelChatRequest:
    return ModelChatRequest(
        model=model,
        messages=[{"role": "user", "content": "hello"}],
        response_format={"type": "json_object"} if structured else None,
    )


def _observe_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[float | None, asyncio.Timeout]]:
    """Observe real asyncio contexts; the tests may expire one after dispatch."""
    observed: list[tuple[float | None, asyncio.Timeout]] = []
    real_timeout = asyncio.timeout

    def timeout(delay: float | None) -> asyncio.Timeout:
        context = real_timeout(delay)
        observed.append((delay, context))
        return context

    monkeypatch.setattr(admitted_model, "asyncio", SimpleNamespace(timeout=timeout))
    return observed


def _freeze_admission_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    class Clock:
        @staticmethod
        def now(_timezone: object) -> datetime:
            return now

    monkeypatch.setattr(admitted_model, "datetime", Clock)


async def test_sdk_pin_structured_payload_and_scoped_credential_cross_canonical_egress() -> None:
    harness = await _setup()
    with bind_execution_context(
        run_id=harness.identity[0],
        node_run_id=harness.identity[1],
        attempt_id=harness.identity[2],
    ):
        result = await harness.consumer().complete(
            request=_request(structured=True), effect_key="answer"
        )
    assert len(harness.sent) == 1
    wire = harness.sent[0]
    assert str(wire.url) == "https://owner.fixture/api/chat/completions"
    assert wire.headers["Authorization"] == "Bearer scoped-fixture-key"
    payload = json.loads(wire.content)
    assert payload["model"] == "acme-precise"  # Binding pin outranks request alias.
    assert payload["response_format"] == {"type": "json_object"}
    assert "scoped-fixture-key" not in wire.content.decode()
    (invocation,) = await harness.history()
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.actor_id == "canonical-actor"
    assert invocation.binding.binding_id == harness.binding.binding_id
    assert invocation.binding.project_id == harness.binding.project_id
    assert (invocation.run_id, invocation.node_run_id, invocation.attempt_id) == harness.identity
    assert result.model == "acme-precise"
    assert result.usage is not None
    assert result.usage.input_units == 7
    assert result.usage.output_units == 3
    assert invocation.usage == result.usage
    assert result.usage.provider == "acme.models"


async def test_unpinned_sdk_call_uses_canonical_router_selection() -> None:
    harness = await _setup(provider_name="")
    result = await harness.consumer().complete(
        request=_request(model=""), identity=harness.identity, effect_key="answer"
    )
    assert result.model == "acme-fast"
    assert json.loads(harness.sent[0].content)["model"] == "acme-fast"


@pytest.mark.parametrize("refusal", ["structured", "health", "unavailable-pin", "foreign-alias"])
async def test_sdk_refusals_remain_canonical_and_dispatch_nothing(refusal: str) -> None:
    harness = await _setup(provider_name="" if refusal == "foreign-alias" else "acme-fast")
    if refusal == "health":
        # Deliberately no availability sync: the catalog backstop must still refuse.
        harness.catalog.note_health("acme.models", False)
    if refusal == "unavailable-pin":
        harness.registry.mark_unavailable("acme-fast")
    with pytest.raises(CapabilityUnavailable):
        await harness.consumer().complete(
            request=_request(
                structured=refusal == "structured",
                model="foreign-model" if refusal == "foreign-alias" else "acme-precise",
            ),
            identity=harness.identity,
            effect_key="answer",
        )
    assert harness.sent == []
    assert await harness.history() == []


async def test_two_consumers_keep_their_own_catalog_when_process_default_changes() -> None:
    harness = await _setup()
    other_catalog, _ = await _catalog(base_url="https://second-owner.fixture/v2")
    first = harness.consumer()
    second = harness.consumer(adapters=other_catalog)
    try:
        configure_default_adapter_catalog(other_catalog)
        await first.complete(request=_request(), identity=harness.identity, effect_key="first")
        configure_default_adapter_catalog(harness.catalog)
        await second.complete(request=_request(), identity=harness.identity, effect_key="second")
    finally:
        release_default_adapter_catalog(other_catalog)
        release_default_adapter_catalog(harness.catalog)
    assert [str(wire.url) for wire in harness.sent] == [
        "https://owner.fixture/api/chat/completions",
        "https://second-owner.fixture/v2/chat/completions",
    ]


async def test_consumer_without_catalog_cannot_borrow_process_default() -> None:
    harness = await _setup()
    try:
        configure_default_adapter_catalog(harness.catalog)
        with pytest.raises(CapabilityUnavailable):
            await harness.consumer(omit_catalog=True).complete(
                request=_request(), identity=harness.identity, effect_key="answer"
            )
    finally:
        release_default_adapter_catalog(harness.catalog)
    assert harness.sent == []
    assert await harness.history() == []


@pytest.mark.parametrize("credential_scope", ["missing", "foreign-workspace", "foreign-project"])
async def test_sdk_credential_scope_cannot_be_replaced_by_endpoint_key(
    credential_scope: str,
) -> None:
    harness = await _setup(credentials=False)
    if credential_scope != "missing":
        harness.effects.credentials.add(
            workspace_id="foreign" if credential_scope == "foreign-workspace" else "workspace",
            project_id="foreign"
            if credential_scope == "foreign-project"
            else harness.binding.project_id,
            record=CredentialRecord(
                key_id="acme-primary", provider="acme", api_key="foreign-fixture-key"
            ),
        )
    with pytest.raises(CredentialScopeError):
        await harness.consumer().complete(
            request=_request(), identity=harness.identity, effect_key="answer"
        )
    assert harness.sent == []
    assert await harness.history() == []


@pytest.mark.parametrize("sdk", [False, True], ids=["gateway", "sdk"])
@pytest.mark.parametrize(
    ("caller_timeout", "remaining", "expected"),
    [(None, None, 120.0), (30.0, None, 30.0), (30.0, 7.0, 7.0), (30.0, 70.0, 30.0)],
)
async def test_call_deadline_bounds_await_but_preserves_sdk_transport_timeout(
    monkeypatch: pytest.MonkeyPatch,
    sdk: bool,
    caller_timeout: float | None,
    remaining: float | None,
    expected: float,
) -> None:
    # Lease validity is checked, but its expiry is not a completion deadline.
    now = datetime.now(UTC)
    harness = await _setup(
        sdk=sdk, deadline_at=now + timedelta(seconds=remaining) if remaining else None
    )
    _freeze_admission_clock(monkeypatch, now)
    observed = _observe_timeouts(monkeypatch)
    await harness.consumer().complete(
        request=_request(),
        identity=harness.identity,
        effect_key="answer",
        timeout_s=caller_timeout,
    )
    assert [duration for duration, _ in observed] == [expected]
    # Actual HTTPX request extensions prove which configured transport won.
    assert set(harness.sent[0].extensions["timeout"].values()) == {11.0 if sdk else expected}


async def test_lease_expiry_is_not_substituted_for_attempt_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _setup()
    now = datetime.now(UTC)
    assert harness.fencing_token is not None
    await harness.runs.renew_lease(
        harness.identity[2],
        fencing_token=harness.fencing_token,
        at=now,
        ttl=timedelta(seconds=2),
    )
    _freeze_admission_clock(monkeypatch, now)
    observed = _observe_timeouts(monkeypatch)
    await harness.consumer().complete(
        request=_request(), identity=harness.identity, effect_key="answer", timeout_s=30.0
    )
    assert [duration for duration, _ in observed] == [30.0]
    assert len(harness.sent) == 1


@pytest.mark.parametrize("termination", ["outer-timeout", "caller-cancel"])
async def test_sdk_post_dispatch_cancellation_is_unknown_and_blocks_later_attempt(
    monkeypatch: pytest.MonkeyPatch, termination: str
) -> None:
    harness = await _setup()
    observed = _observe_timeouts(monkeypatch)

    async def suspended_dispatch(wire: httpx.Request) -> httpx.Response:
        harness.sent.append(wire)
        assert len(observed) == 1
        if termination == "outer-timeout":
            observed[0][1].reschedule(asyncio.get_running_loop().time())
        else:
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
        await asyncio.Event().wait()
        raise AssertionError("cancelled HTTP dispatch unexpectedly resumed")

    set_test_transport(httpx.MockTransport(suspended_dispatch))
    calls = harness.consumer()
    call = asyncio.create_task(
        calls.complete(
            request=_request(), identity=harness.identity, effect_key="answer", timeout_s=30.0
        )
    )
    with pytest.raises(TimeoutError if termination == "outer-timeout" else asyncio.CancelledError):
        await call
    assert len(harness.sent) == 1
    assert observed[0][0] == 30.0
    assert set(harness.sent[0].extensions["timeout"].values()) == {11.0}
    (invocation,) = await harness.history()
    assert invocation.status is InvocationStatus.UNKNOWN
    assert invocation.attempt_id == harness.identity[2]
    event = await harness.effects.event_store.get(
        f"capability-invocation-{invocation.invocation_id}-unknown"
    )
    assert event is not None
    assert event.invocation_id == invocation.invocation_id
    assert event.attempt_id == harness.identity[2]
    policy = await harness.effects.event_store.get(event.causation_id)
    assert policy is not None
    assert policy.type == "capability.invocation.policy_decision"
    assert policy.payload["effect_key"] == "answer"
    retry_identity = await harness.next_attempt()
    with pytest.raises(UnsafeEffectRetry, match="unknown"):
        await calls.complete(
            request=_request(), identity=retry_identity, effect_key="answer", timeout_s=30.0
        )
    assert len(harness.sent) == 1
    assert await harness.history() == [invocation]


async def test_sdk_proven_non_application_can_retry_same_effect_on_later_attempt() -> None:
    harness = await _setup()

    def connect_then_succeed(wire: httpx.Request) -> httpx.Response:
        harness.sent.append(wire)
        if len(harness.sent) == 1:
            raise httpx.ConnectError("fixture failed before connection", request=wire)
        return httpx.Response(200, json=_RESPONSE)

    set_test_transport(httpx.MockTransport(connect_then_succeed))
    calls = harness.consumer()
    with pytest.raises(EffectNotApplied, match="no effect occurred"):
        await calls.complete(request=_request(), identity=harness.identity, effect_key="answer")
    (failed,) = await harness.history()
    assert failed.status is InvocationStatus.FAILED
    result = await calls.complete(
        request=_request(), identity=await harness.next_attempt(), effect_key="answer"
    )
    history = await harness.history()
    assert [item.status for item in history] == [
        InvocationStatus.FAILED,
        InvocationStatus.COMPLETED,
    ]
    assert history[1].invocation_id == result.invocation_id
    assert history[1].attempt_id != failed.attempt_id
    assert len(harness.sent) == 2


@pytest.mark.parametrize("timeout_s", [0.0, -1.0, float("nan"), float("inf"), -float("inf")])
async def test_nonfinite_or_nonpositive_timeout_refuses_before_dispatch(timeout_s: float) -> None:
    harness = await _setup()
    with pytest.raises(ValueError, match="finite and positive"):
        await harness.consumer().complete(
            request=_request(),
            identity=harness.identity,
            effect_key="answer",
            timeout_s=timeout_s,
        )
    assert harness.sent == []
    assert await harness.history() == []


@pytest.mark.parametrize("remaining", [-1, 0])
async def test_expired_persisted_attempt_deadline_refuses_before_dispatch(
    monkeypatch: pytest.MonkeyPatch, remaining: int
) -> None:
    now = datetime.now(UTC)
    harness = await _setup(deadline_at=now + timedelta(seconds=remaining))
    _freeze_admission_clock(monkeypatch, now)
    with pytest.raises(RunIntegrityError, match="deadline has expired"):
        await harness.consumer().complete(
            request=_request(), identity=harness.identity, effect_key="answer", timeout_s=30.0
        )
    assert harness.sent == []
    assert await harness.history() == []


@pytest.mark.parametrize(
    "record", ["run", "node", "attempt", "missing", "unleased", "lease-expired"]
)
async def test_invalid_execution_authority_never_dispatches(
    monkeypatch: pytest.MonkeyPatch, record: str
) -> None:
    harness = await _setup(leased=record != "unleased")
    identity = harness.identity
    if record == "run":
        await harness.runs.transition_run(identity[0], RunStatus.CANCELLED)
    elif record == "node":
        await harness.runs.transition_node_run(identity[1], RunStatus.CANCELLED)
    elif record == "attempt":
        await harness.runs.transition_attempt(
            identity[2], AttemptStatus.CANCELLED, fencing_token=harness.fencing_token
        )
    elif record == "missing":
        identity = ("unpersisted-run", "unpersisted-node", "unpersisted-attempt")
    elif record == "lease-expired":
        attempt = await harness.runs.get_attempt(identity[2])
        assert attempt is not None and attempt.execution_lease is not None
        assert attempt.execution_lease.expires_at is not None
        _freeze_admission_clock(monkeypatch, attempt.execution_lease.expires_at)
    with pytest.raises(RunIntegrityError):
        await harness.consumer().complete(
            request=_request(), identity=identity, effect_key="answer"
        )
    assert harness.sent == []
    assert await harness.history() == []


@pytest.mark.parametrize("field", ["workspace_id", "project_id", "run_id", "attempt_id"])
async def test_live_context_cannot_override_persisted_execution_scope(field: str) -> None:
    harness = await _setup()
    with bind_execution_context(**{field: "foreign"}), pytest.raises(RunIntegrityError):
        await harness.consumer().complete(
            request=_request(), identity=harness.identity, effect_key="answer"
        )
    assert harness.sent == []


@pytest.mark.parametrize("mismatch", ["node-run", "attempt-node", "blank"])
async def test_record_links_and_nonempty_identity_are_required(mismatch: str) -> None:
    harness = await _setup()
    original_run = await harness.runs.get_run(harness.identity[0])
    assert original_run is not None
    other_run = await harness.runs.create_run(
        original_run.graph.materialize(),
        actor_principal_id="other-actor",
        initial_status=RunStatus.QUEUED,
    )
    await harness.runs.transition_run(other_run.run_id, RunStatus.RUNNING)
    other_node = await harness.runs.create_node_run(other_run.run_id, node_id="chat")
    for step in transition_path(other_node.status, RunStatus.RUNNING):
        other_node = await harness.runs.transition_node_run(other_node.node_run_id, step)
    other_attempt = await harness.runs.create_attempt(
        other_node.node_run_id, lease_holder="other-worker", lease_ttl=timedelta(hours=1)
    )
    assert other_attempt.execution_lease is not None
    await harness.runs.transition_attempt(
        other_attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=other_attempt.execution_lease.fencing_token,
    )
    identity = {
        "node-run": (harness.identity[0], other_node.node_run_id, other_attempt.attempt_id),
        "attempt-node": (harness.identity[0], harness.identity[1], other_attempt.attempt_id),
        "blank": ("", "", ""),
    }[mismatch]
    with pytest.raises(RunIntegrityError):
        await harness.consumer().complete(
            request=_request(), identity=identity, effect_key="answer"
        )
    assert harness.sent == []
    assert await harness.history() == []


@pytest.mark.parametrize(
    "condition", ["unconfigured", "revoked", "disabled", "ambiguous", "undeclared"]
)
async def test_binding_authority_is_resolved_again_on_every_call(condition: str) -> None:
    harness = await _setup(disabled=condition == "disabled")
    ids = (harness.binding.binding_id,)
    selected = ""
    if condition == "unconfigured":
        ids = ()
    elif condition == "ambiguous":
        other = harness.binding.model_copy(update={"binding_id": "other"})
        await harness.effects.bindings.put(other)
        ids += (other.binding_id,)
    elif condition == "undeclared":
        other = harness.binding.model_copy(update={"binding_id": "other"})
        await harness.effects.bindings.put(other)
        selected = other.binding_id
    calls = harness.consumer(binding_ids=ids)
    if condition == "revoked":
        await harness.effects.bindings.revoke(harness.binding.binding_id)
    with pytest.raises(BindingResolutionError):
        await calls.complete(
            request=_request(), identity=harness.identity, effect_key="answer", binding_id=selected
        )
    assert harness.sent == []
    assert await harness.history() == []


async def test_successful_consumer_does_not_cache_revoked_binding_authority() -> None:
    harness = await _setup()
    calls = harness.consumer()
    await calls.complete(request=_request(), identity=harness.identity, effect_key="answer")
    await harness.effects.bindings.revoke(harness.binding.binding_id)
    with pytest.raises(BindingResolutionError):
        await calls.complete(
            request=_request(), identity=harness.identity, effect_key="next-answer"
        )
    assert len(harness.sent) == 1


@pytest.mark.parametrize("scope", ["workspace_id", "project_id", "node_id", "capability"])
async def test_configured_binding_must_cover_actual_run_and_node(scope: str) -> None:
    harness = await _setup()
    foreign = harness.binding.model_copy(update={"binding_id": "foreign", scope: "foreign"})
    await harness.effects.bindings.put(foreign)
    with pytest.raises(BindingResolutionError):
        await harness.consumer(binding_ids=(foreign.binding_id,)).complete(
            request=_request(), identity=harness.identity, effect_key="answer"
        )
    assert harness.sent == []
    assert await harness.history() == []


async def test_canonical_policy_denial_remains_before_dispatch() -> None:
    harness = await _setup()

    async def deny(*_args: object) -> PolicyVerdict:
        return PolicyVerdict(Decision.DENY, reason="fixture operator denial")

    harness.effects = harness.effects.with_policy_evaluator(deny)
    with pytest.raises(InvocationDenied, match="operator denial"):
        await harness.consumer().complete(
            request=_request(), identity=harness.identity, effect_key="answer"
        )
    assert harness.sent == []
    assert await harness.history() == []
