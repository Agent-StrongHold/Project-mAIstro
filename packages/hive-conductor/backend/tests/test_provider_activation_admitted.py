"""Provider activation uses real SQLite authorities and terminal HTTP/vault fakes."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from routes import providers
from services import governed_model
from starlette.requests import Request

from maistro.container import Container, create_container
from maistro.http import set_test_transport
from maistro.identity import Principal
from maistro.observability.correlation import current_execution_context
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.types.config import AgentConfig

WORKSPACE = "activation-workspace"
ACTOR = "activation-operator"
MODEL = "groq/llama-3.3-70b-versatile"
BINDING = "provider-activation:groq"
PROVIDER_KEY = "sentinel-provider-secret"
ADMIN_KEY = "sentinel-admin-secret"


class Vault:
    def has(self, name: str) -> bool:
        assert name == "GROQ_API_KEY"
        return True

    def use(self, name: str, callback: Callable[[str], Any]) -> Any:
        assert name == "GROQ_API_KEY"
        return callback(PROVIDER_KEY)


@dataclass
class Setup:
    owner: Container
    runtime: governed_model.GovernedModelRuntime
    path: Path
    project_id: str
    requests: list[httpx.Request] = field(default_factory=list)
    live: list[Any] = field(default_factory=list)
    activated: list[str] = field(default_factory=list)
    responder: Callable[[httpx.Request], Any] | None = None

    async def activate(self) -> dict[str, Any]:
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        request.state.principal = Principal(user_id=ACTOR)
        return await providers.activate_provider("groq", request)

    async def runs(self) -> list[Any]:
        return [
            run
            for status in RunStatus
            for run in await self.owner.run_store.list_by_status(status)
            if run.provenance.get("operation") == BINDING
        ]

    def persisted(self) -> str:
        with sqlite3.connect(self.path) as db:
            return "\n".join(db.iterdump())


@pytest.fixture
async def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Setup]:
    import config

    path = tmp_path / "runtime.sqlite3"
    owner = await create_container(
        AgentConfig(database_url=f"sqlite:///{path}", router_api_key="test-router-key")
    )
    await owner.workspace_store.create(
        name="Activation", creator_user_id=ACTOR, workspace_id=WORKSPACE
    )
    root = await owner.project_scope_store.root_for_workspace(WORKSPACE)
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro.providers.types import ModelMetadata

    owner.provider_registry.register_model(
        ModelMetadata(
            name=MODEL,
            provider="groq",
            cost_per_1k_input=0.5,
            cost_per_1k_output=1.0,
            latency_p50_ms=1,
        )
    )
    runtime = governed_model.GovernedModelRuntime(
        effects=owner.capability_effects,
        registry=owner.provider_registry,
        router=owner.llm_router,
        endpoint=GatewayEndpoint(base_url="https://activation.gateway.test", api_key=ADMIN_KEY),
        project_scope_store=owner.project_scope_store,
        run_store=owner.run_store,
    )
    state = Setup(owner, runtime, path, root.project_id)
    monkeypatch.setattr(governed_model, "_runtime", lambda: state.runtime)
    monkeypatch.setattr(
        config, "get_settings", lambda: SimpleNamespace(hive_default_workspace_id=WORKSPACE)
    )
    monkeypatch.setattr(providers, "_vault", Vault)
    monkeypatch.setattr(providers, "_record_activation", state.activated.append)

    async def transport(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        context = current_execution_context()
        state.live.append(
            await owner.run_store.get_attempt(context.attempt_id) if context.attempt_id else None
        )
        if state.responder is not None:
            return await state.responder(request)
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"content": "pong"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )

    set_test_transport(httpx.MockTransport(transport))
    try:
        yield state
    finally:
        set_test_transport(None)
        await owner.aclose()


async def test_activation_has_live_admitted_actor_scope_lease_and_safe_evidence(
    setup: Setup,
) -> None:
    result = await setup.activate()
    assert result["activated"] is True
    assert len(setup.requests) == 2
    assert all(attempt is not None for attempt in setup.live)
    for attempt in setup.live:
        assert attempt.status is AttemptStatus.RUNNING
        assert attempt.execution_lease.expires_at > datetime.now(UTC)
    (run,) = await setup.runs()
    assert run.parent_run_id is None
    assert run.actor_principal_id == ACTOR
    assert run.workspace_id == WORKSPACE and run.project_id == setup.project_id
    (node,) = run.graph.materialize().nodes
    assert node.node_id == "control-plane" and node.node_type == "capability"
    assert node.binding_ids == [BINDING]
    (node_run,) = await setup.owner.run_store.list_node_runs(run.run_id)
    (attempt,) = await setup.owner.run_store.list_attempts(node_run.node_run_id)
    assert run.status is node_run.status is RunStatus.COMPLETED
    assert attempt.status is AttemptStatus.COMPLETED
    invocation = await setup.owner.invocation_store.get(result["first_model_call"]["invocation_id"])
    assert invocation.actor_id == ACTOR
    assert invocation.attempt_id == attempt.attempt_id
    assert attempt.result == {"invocation_id": invocation.invocation_id, "model": MODEL}
    assert json.loads(setup.requests[1].content)["max_tokens"] == 1
    assert PROVIDER_KEY not in setup.persisted()
    assert ADMIN_KEY not in setup.persisted()


async def test_repeat_activation_reuses_first_binding_but_dispatches_fresh_probe(
    setup: Setup,
) -> None:
    first = await setup.activate()
    original = await setup.owner.capability_effects.bindings.get(BINDING)
    second = await setup.activate()
    assert await setup.owner.capability_effects.bindings.get(BINDING) == original
    assert first["first_model_call"]["invocation_id"] != second["first_model_call"]["invocation_id"]
    assert len(setup.requests) == 4
    assert len(await setup.runs()) == 2


def _definition(s: Setup, **changes: Any) -> Any:
    return governed_model.control_plane_binding_definition(
        binding_id=BINDING, workspace_id=WORKSPACE, project_id=s.project_id, provider_name=MODEL
    ).model_copy(update=changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"disabled": True},
        {"provider_name": "wrong-model"},
        {"workspace_id": "foreign"},
        {"project_id": "foreign"},
        {"node_id": "foreign"},
        {"config": {"changed": True}},
        {"credential_refs": ()},
        {"policy_refs": ("changed",)},
    ],
)
async def test_immutable_binding_refusal_does_not_refresh_credential(
    setup: Setup, changes: dict[str, Any]
) -> None:
    from maistro.capabilities.providers.llm_gateway import MODEL_GATEWAY_CREDENTIAL_PROVIDER
    from maistro.credentials.types import CredentialRecord

    original = await setup.runtime.effects.bindings.put(_definition(setup, **changes))
    record = CredentialRecord(
        key_id="litellm-gateway",
        provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
        api_key="existing-scoped-secret",
    )
    setup.runtime.effects.credentials.add(
        workspace_id=WORKSPACE, project_id=setup.project_id, record=record
    )
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 403
    assert await setup.runtime.effects.bindings.get(BINDING) == original
    assert record.api_key == "existing-scoped-secret"
    assert setup.requests == setup.activated == []


async def test_revocation_tombstone_survives_activation(setup: Setup) -> None:
    await setup.runtime.effects.bindings.put(_definition(setup))
    await setup.runtime.effects.bindings.revoke(BINDING)
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 403
    assert await setup.runtime.effects.bindings.get(BINDING) is None
    assert (
        setup.runtime.effects.credentials.pool_for(
            workspace_id=WORKSPACE, project_id=setup.project_id, provider="litellm"
        )
        is None
    )
    assert setup.requests == setup.activated == []


@pytest.mark.parametrize("decision", ["deny", "require_approval"])
async def test_policy_refusal_is_cancelled_without_setup(setup: Setup, decision: str) -> None:
    import asyncio
    from dataclasses import replace

    from maistro.policy.types import Decision, PolicyVerdict

    async def policy(*args: Any) -> Any:
        return PolicyVerdict(Decision(decision), reason="fixture", rule="fixture")

    setup.runtime = replace(
        setup.runtime, effects=setup.runtime.effects.with_policy_evaluator(policy)
    )
    cancelling = asyncio.current_task().cancelling()
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 403
    assert asyncio.current_task().cancelling() == cancelling
    (run,) = await setup.runs()
    assert run.status is RunStatus.CANCELLED
    assert setup.requests == setup.activated == []


async def _budget(setup: Setup, limit: int, unit: str = "requests") -> Any:
    from maistro.quota.invocation_quota import QuotaBudget

    quota = setup.runtime.effects.quota
    await quota.register_budget(
        QuotaBudget(
            budget_id="activation-budget",
            unit=unit,
            limit=limit,
            period_start=0,
            period_end=2**62,
            coverage_ref="fixture-opening",
            opening_spend=0,
            workspace_id=WORKSPACE,
            principal_id=ACTOR,
            capability="model.chat",
        )
    )
    return quota


@pytest.mark.parametrize("unit", ["requests", "tokens", "micro_usd"])
async def test_actor_quota_refuses_before_registration(setup: Setup, unit: str) -> None:
    await _budget(setup, 0 if unit == "requests" else 1000000, unit)
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 502
    assert setup.requests == setup.activated == []
    (run,) = await setup.runs()
    assert run.status is RunStatus.FAILED


async def test_actor_request_budget_is_charged_once_then_refuses_new_operation(
    setup: Setup,
) -> None:
    quota = await _budget(setup, 1)
    await setup.activate()
    with pytest.raises(HTTPException):
        await setup.activate()
    balance = await quota.balance("activation-budget")
    assert balance.spent == 1 and balance.held == 0
    assert len(setup.requests) == 2 and setup.activated == ["groq"]
    assert len(await setup.runs()) == 2


@pytest.mark.parametrize("phase", ["registration", "probe", "probe-connect", "registration-auth"])
async def test_provider_failures_keep_unknown_hold_and_no_secrets(
    setup: Setup, caplog: Any, phase: str
) -> None:
    from maistro.capabilities.invocation import InvocationStatus
    from maistro.capabilities.providers.llm_gateway import LlmAuthError

    quota = await _budget(setup, 1)
    caplog.set_level("DEBUG")

    async def respond(request: httpx.Request) -> httpx.Response:
        if phase.startswith("registration") or request.url.path.endswith("completions"):
            if phase == "registration-auth":
                raise LlmAuthError(PROVIDER_KEY, status_code=401)
            if phase == "probe-connect":
                raise httpx.ConnectError(PROVIDER_KEY, request=request)
            raise httpx.ReadTimeout(PROVIDER_KEY, request=request)
        return httpx.Response(200, json={})

    setup.responder = respond
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 502
    assert PROVIDER_KEY not in str(caught.value)
    (run,) = await setup.runs()
    assert run.status is RunStatus.FAILED
    (node,) = await setup.owner.run_store.list_node_runs(run.run_id)
    (attempt,) = await setup.owner.run_store.list_attempts(node.node_run_id)
    assert node.status is RunStatus.FAILED and attempt.status is AttemptStatus.FAILED
    (invocation,) = await setup.owner.invocation_store.list_effect(
        run_id=run.run_id,
        node_run_id=node.node_run_id,
        binding_id=BINDING,
        effect_key=f"provider.health:{MODEL}",
    )
    assert invocation.status is InvocationStatus.UNKNOWN
    balance = await quota.balance("activation-budget")
    assert balance.held == 1 and balance.spent == 0
    assert setup.activated == []
    assert PROVIDER_KEY not in setup.persisted() + caplog.text
    assert ADMIN_KEY not in setup.persisted() + caplog.text
    if phase.startswith("registration"):
        stats = setup.runtime.effects.credentials.stats(
            workspace_id=WORKSPACE, project_id=setup.project_id, provider="litellm"
        )
        assert stats.blocked_keys == 0 and stats.total_error_count == 0


async def test_secret_disappearing_after_has_cancels_real_operation(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.vault import SecretMissingError

    class Vanished(Vault):
        def use(self, name: str, callback: Any) -> Any:
            raise SecretMissingError(PROVIDER_KEY)

    monkeypatch.setattr(providers, "_vault", Vanished)
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 409
    (run,) = await setup.runs()
    assert run.status is RunStatus.CANCELLED
    assert setup.requests == setup.activated == []
    assert PROVIDER_KEY not in setup.persisted()


@pytest.mark.parametrize("phase", ["registration", "probe"])
async def test_actual_cancellation_signals_live_provider_and_settles_unknown(
    setup: Setup, phase: str
) -> None:
    import asyncio

    started, stopped = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        if phase == "registration" or request.url.path.endswith("completions"):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        return httpx.Response(200, json={})

    setup.responder = respond
    task = asyncio.create_task(setup.activate())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.wait_for(stopped.wait(), 2)
    with pytest.raises(asyncio.CancelledError):
        await task
    (run,) = await setup.runs()
    assert run.status is RunStatus.CANCELLED
    (node,) = await setup.owner.run_store.list_node_runs(run.run_id)
    (attempt,) = await setup.owner.run_store.list_attempts(node.node_run_id)
    assert node.status is RunStatus.CANCELLED and attempt.status is AttemptStatus.CANCELLED
    assert setup.activated == []


def _delay_activation_write(setup: Setup, monkeypatch: pytest.MonkeyPatch, phase: str) -> Any:
    import asyncio

    from maistro.runs.service import RunExecutionService

    entered, release, fenced = asyncio.Event(), asyncio.Event(), asyncio.Event()
    target = RunExecutionService if phase == "admission" else type(setup.owner.run_store)
    method = {
        "admission": "create_run",
        "attempt": "transition_attempt",
        "node": "transition_node_run",
        "run": "transition_run",
    }[phase]
    original = getattr(target, method)
    delayed = False

    async def delayed_write(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal delayed
        is_terminal = phase == "admission" or (len(args) > 1 and args[1].value == "completed")
        if is_terminal and not delayed:
            delayed = True
            if phase == "admission":
                result = await original(self, *args, **kwargs)
                entered.set()
                await release.wait()
                return result
            entered.set()
            await release.wait()
        result = await original(self, *args, **kwargs)
        if method == "transition_run" and args[1] is RunStatus.CANCELLED:
            fenced.set()
        return result

    original_run_transition = type(setup.owner.run_store).transition_run
    if method != "transition_run":

        async def mark_fenced(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = await original_run_transition(self, *args, **kwargs)
            if args[1] is RunStatus.CANCELLED:
                fenced.set()
            return result

        monkeypatch.setattr(type(setup.owner.run_store), "transition_run", mark_fenced)

    monkeypatch.setattr(target, method, delayed_write)
    return entered, release, fenced


@pytest.mark.parametrize("phase", ["admission", "attempt", "node", "run"])
async def test_cancellation_drains_durable_write_and_never_sets_activation(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    import asyncio

    entered, release, fenced = _delay_activation_write(setup, monkeypatch, phase)
    task = asyncio.create_task(setup.activate())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    if phase != "admission":
        await asyncio.wait_for(fenced.wait(), 2)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    (run,) = await setup.runs()
    assert run.status is RunStatus.CANCELLED
    for node in await setup.owner.run_store.list_node_runs(run.run_id):
        assert node.status in {RunStatus.CANCELLED, RunStatus.COMPLETED}
        for attempt in await setup.owner.run_store.list_attempts(node.node_run_id):
            assert attempt.status in {AttemptStatus.CANCELLED, AttemptStatus.COMPLETED}
    assert setup.activated == []
    if phase == "admission":
        assert setup.requests == []


async def _explicit_activation(
    setup: Setup, binding: Any, *, models: tuple[str, ...] = (MODEL,)
) -> Any:
    from services.provider_activation import activate

    return await activate(
        runtime=setup.runtime,
        binding=binding,
        actor_principal_id=ACTOR,
        name="groq",
        provider_name=MODEL,
        models=models,
        vault=Vault(),
        secret_name="GROQ_API_KEY",
    )


async def _probe_binding(setup: Setup, *, key: bool = True, **changes: Any) -> Any:
    from maistro.credentials.types import CredentialRecord

    binding = await setup.runtime.effects.bindings.put(
        _definition(setup, credential_refs=("scoped-probe",), **changes)
    )
    if key:
        setup.runtime.effects.credentials.add(
            workspace_id=WORKSPACE,
            project_id=setup.project_id,
            record=CredentialRecord(
                key_id="scoped-probe", provider="litellm", api_key="scoped-probe-secret"
            ),
        )
    return binding


@pytest.mark.parametrize("problem", ["missing-key", "blocked", "cooling", "wrong-pin"])
async def test_admitted_health_refuses_without_repairing_grants_or_credentials(
    setup: Setup, problem: str
) -> None:
    from maistro.capabilities.providers.llm_gateway import LlmAuthError, LlmHttpError

    binding = await _probe_binding(
        setup,
        key=problem != "missing-key",
        **({"provider_name": "other"} if problem == "wrong-pin" else {}),
    )
    if problem in {"blocked", "cooling"}:
        await setup.runtime.effects.credentials.record_outcome(
            workspace_id=WORKSPACE,
            project_id=setup.project_id,
            provider="litellm",
            key_id="scoped-probe",
            error=LlmAuthError("denied", status_code=401)
            if problem == "blocked"
            else LlmHttpError("limited", status_code=429),
        )
    with pytest.raises(
        (governed_model.ProviderAuthorizationError, governed_model.ProviderHealthError)
    ):
        await _explicit_activation(setup, binding)
    assert setup.requests == []
    assert await setup.runtime.effects.bindings.get(BINDING) == binding
    (run,) = await setup.runs()
    assert run.status in {RunStatus.CANCELLED, RunStatus.FAILED}


@pytest.mark.parametrize("status", [200, 401, 429])
async def test_registration_admin_and_scoped_probe_credentials_are_separate(
    setup: Setup, status: int
) -> None:
    binding = await _probe_binding(setup)

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/model/new":
            assert request.headers["Authorization"] == f"Bearer {ADMIN_KEY}"
            return httpx.Response(200, json={})
        assert request.headers["Authorization"] == "Bearer scoped-probe-secret"
        return httpx.Response(status, json={"choices": [{"message": {"content": "pong"}}]})

    setup.responder = respond
    if status == 200:
        await _explicit_activation(setup, binding)
    else:
        with pytest.raises(governed_model.ProviderHealthError):
            await _explicit_activation(setup, binding)
    stats = setup.runtime.effects.credentials.stats(
        workspace_id=WORKSPACE, project_id=setup.project_id, provider="litellm"
    )
    assert stats.blocked_keys == int(status == 401)
    assert stats.cooling_down_keys == int(status == 429)
    assert len(setup.requests) == 2


async def test_partial_admin_registration_never_poison_scoped_probe_or_retries(
    setup: Setup,
) -> None:
    binding = await _probe_binding(setup)

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/model/new"
        return httpx.Response(200 if len(setup.requests) == 1 else 401, json={})

    setup.responder = respond
    with pytest.raises(governed_model.ProviderActivationError):
        await _explicit_activation(setup, binding, models=(MODEL, "groq/another-fixed-model"))
    stats = setup.runtime.effects.credentials.stats(
        workspace_id=WORKSPACE, project_id=setup.project_id, provider="litellm"
    )
    assert stats.available_keys == 1 and stats.total_error_count == 0
    assert len(setup.requests) == 2


async def test_failure_settlement_respects_concurrent_cancellation(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = setup.owner.run_store.transition_node_run
    won = False

    async def raced(node_id: str, status: Any, **kwargs: Any) -> Any:
        nonlocal won
        if status is RunStatus.RUNNING and not won:
            node = await setup.owner.run_store.get_node_run(node_id)
            if node.status is RunStatus.WAITING:
                won = True
                await original(node_id, RunStatus.CANCELLED)
                await setup.owner.run_store.transition_run(node.run_id, RunStatus.CANCELLED)
        return await original(node_id, status, **kwargs)

    async def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    setup.responder = reject
    monkeypatch.setattr(setup.owner.run_store, "transition_node_run", raced)
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 502 and won
    (run,) = await setup.runs()
    (node,) = await setup.owner.run_store.list_node_runs(run.run_id)
    (attempt,) = await setup.owner.run_store.list_attempts(node.node_run_id)
    assert run.status is node.status is RunStatus.CANCELLED
    assert attempt.status is AttemptStatus.FAILED


async def test_cancel_fence_failure_still_signals_actual_runtime(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    import asyncio

    started, stopped = asyncio.Event(), asyncio.Event()

    async def wait(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
        raise AssertionError("unreachable")

    setup.responder = wait
    original = setup.owner.run_store.transition_run
    failed = False

    async def fail_once(run_id: str, status: Any, **kwargs: Any) -> Any:
        nonlocal failed
        if status is RunStatus.CANCELLED and not failed:
            failed = True
            raise RuntimeError(PROVIDER_KEY)
        return await original(run_id, status, **kwargs)

    monkeypatch.setattr(setup.owner.run_store, "transition_run", fail_once)
    task = asyncio.create_task(setup.activate())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.wait_for(stopped.wait(), 2)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    (run,) = await setup.runs()
    assert run.status is RunStatus.CANCELLED
    assert setup.activated == []
    assert "cancellation fence unavailable" in caplog.text
    assert PROVIDER_KEY not in caplog.text


async def test_authority_checks_precede_quota_registration_and_probe(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from maistro.policy.types import Decision, PolicyVerdict

    order: list[str] = []

    async def policy(*args: Any) -> Any:
        order.append("policy")
        return PolicyVerdict(Decision.ALLOW, reason="fixture", rule="fixture")

    setup.runtime = replace(
        setup.runtime, effects=setup.runtime.effects.with_policy_evaluator(policy)
    )
    acquire = setup.runtime.effects.credentials.acquire
    reserve = setup.runtime.effects.quota.reserve

    async def checked_acquire(**kwargs: Any) -> Any:
        order.append("credential")
        return await acquire(**kwargs)

    async def checked_reserve(*args: Any, **kwargs: Any) -> Any:
        order.append("quota")
        return await reserve(*args, **kwargs)

    async def respond(request: httpx.Request) -> httpx.Response:
        order.append("registration" if request.url.path == "/model/new" else "probe")
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    monkeypatch.setattr(setup.runtime.effects.credentials, "acquire", checked_acquire)
    monkeypatch.setattr(setup.runtime.effects.quota, "reserve", checked_reserve)
    setup.responder = respond
    await setup.activate()
    assert order == ["policy", "credential", "quota", "registration", "probe"]


async def test_transport_returning_after_cancel_cannot_mark_activation(setup: Setup) -> None:
    import asyncio
    from contextlib import suppress

    started = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("completions"):
            started.set()
            with suppress(asyncio.CancelledError):
                await asyncio.Event().wait()
        return httpx.Response(
            200, json={"model": MODEL, "choices": [{"message": {"content": "late"}}]}
        )

    setup.responder = respond
    task = asyncio.create_task(setup.activate())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    (run,) = await setup.runs()
    assert run.status is RunStatus.CANCELLED and setup.activated == []


async def test_missing_run_store_refuses_without_provider_work(setup: Setup) -> None:
    from dataclasses import replace

    setup.runtime = replace(setup.runtime, run_store=None)
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 503
    assert setup.requests == setup.activated == []


async def test_arbitrary_vault_callback_error_is_sanitized(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailedVault(Vault):
        def use(self, name: str, callback: Any) -> Any:
            raise RuntimeError(PROVIDER_KEY)

    monkeypatch.setattr(providers, "_vault", FailedVault)
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 502
    (run,) = await setup.runs()
    assert run.status is RunStatus.FAILED
    assert PROVIDER_KEY not in setup.persisted()
    assert setup.requests == []


async def test_persistent_cleanup_failure_preserves_cancellation_and_safe_diagnostic(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    import asyncio

    started = asyncio.Event()

    async def wait(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    setup.responder = wait
    original = setup.owner.run_store.transition_run

    async def unavailable(run_id: str, status: Any, **kwargs: Any) -> Any:
        if status is RunStatus.CANCELLED:
            raise RuntimeError(PROVIDER_KEY)
        return await original(run_id, status, **kwargs)

    monkeypatch.setattr(setup.owner.run_store, "transition_run", unavailable)
    task = asyncio.create_task(setup.activate())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert "cancellation fence unavailable" in caplog.text
    assert PROVIDER_KEY not in caplog.text + setup.persisted()
    assert setup.activated == []


async def test_bad_status_metadata_cannot_reintroduce_secret_context(
    setup: Setup, caplog: Any
) -> None:
    from maistro.capabilities.providers.llm_gateway import LlmHttpError

    binding = await _probe_binding(setup)

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("completions"):
            error = LlmHttpError(PROVIDER_KEY, status_code=500)
            error.status_code = "malformed"  # type: ignore[assignment]
            raise error
        return httpx.Response(200, json={})

    setup.responder = respond
    with pytest.raises(governed_model.ProviderHealthError):
        await _explicit_activation(setup, binding)
    assert PROVIDER_KEY not in setup.persisted() + caplog.text


async def test_service_heartbeat_renews_live_physical_lease(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from datetime import timedelta

    from services import provider_activation

    renewed = asyncio.Event()
    original = setup.owner.run_store.renew_lease

    async def renew(*args: Any, **kwargs: Any) -> Any:
        record = await original(*args, **kwargs)
        renewed.set()
        return record

    monkeypatch.setattr(setup.owner.run_store, "renew_lease", renew)
    monkeypatch.setattr(provider_activation, "_ACTIVATION_LEASE_TTL", timedelta(seconds=0.09))

    async def respond(request: httpx.Request) -> httpx.Response:
        await asyncio.wait_for(renewed.wait(), 2)
        current = await setup.owner.run_store.get_attempt(current_execution_context().attempt_id)
        assert current.execution_lease.expires_at > setup.live[0].execution_lease.expires_at
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    setup.responder = respond
    await setup.activate()
    assert renewed.is_set()


async def test_missing_admitted_execution_never_runs_internal_setup(setup: Setup) -> None:
    from dataclasses import replace

    binding = await _probe_binding(setup)
    for runtime in (setup.runtime, replace(setup.runtime, run_store=None)):
        with pytest.raises((RuntimeError, governed_model.ProviderHealthError)):
            await governed_model.register_and_health_check(
                runtime=runtime,
                binding=binding,
                run_id="not-admitted",
                node_run_id="not-admitted",
                attempt_id="not-admitted",
                provider_name=MODEL,
                models=(MODEL,),
                api_key=PROVIDER_KEY,
            )
    assert setup.requests == []


@pytest.mark.parametrize("outcome", ["success", "probe-error", "setup-error"])
async def test_reclaimed_attempt_late_success_closes_operation_without_rewriting_evidence(
    setup: Setup,
    outcome: str,
) -> None:
    from datetime import timedelta

    from maistro.runs.lifecycle import is_reclaimed_attempt
    from maistro.runs.reconciliation import AttemptLifecycleReconciler

    quota = await _budget(setup, 1)
    reclaimed: list[Any] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        if outcome == "setup-error" or request.url.path.endswith("completions"):
            attempt = await setup.owner.run_store.get_attempt(
                current_execution_context().attempt_id
            )
            reclaimed.extend(
                await setup.owner.run_store.reclaim_expired_attempts(
                    now=attempt.execution_lease.expires_at + timedelta(seconds=1)
                )
            )
            assert len(reclaimed) == 1
            await AttemptLifecycleReconciler(setup.owner.run_store).reconcile(reclaimed[0])
            if outcome != "success":
                raise httpx.ReadTimeout(PROVIDER_KEY, request=request)
        return httpx.Response(
            200, json={"model": MODEL, "choices": [{"message": {"content": "late"}}]}
        )

    setup.responder = respond
    with pytest.raises(HTTPException) as caught:
        await setup.activate()
    assert caught.value.status_code == 502 and "lease was reclaimed" in caught.value.detail
    current = await setup.owner.run_store.get_attempt(reclaimed[0].attempt_id)
    assert current == reclaimed[0] and is_reclaimed_attempt(current)
    (run,) = await setup.runs()
    (node,) = await setup.owner.run_store.list_node_runs(run.run_id)
    assert run.status is node.status is RunStatus.FAILED
    assert len(setup.requests) == (1 if outcome == "setup-error" else 2)
    assert setup.activated == []

    from maistro.capabilities.invocation import InvocationStatus

    (invocation,) = await setup.owner.invocation_store.list_effect(
        run_id=run.run_id,
        node_run_id=node.node_run_id,
        binding_id=BINDING,
        effect_key=f"provider.health:{MODEL}",
    )
    assert invocation.status is (
        InvocationStatus.COMPLETED if outcome == "success" else InvocationStatus.UNKNOWN
    )
    balance = await quota.balance("activation-budget")
    assert balance.held == int(outcome != "success")
    assert PROVIDER_KEY not in setup.persisted()


async def test_cancellation_drains_reclaimed_failure_disposition(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from datetime import timedelta

    from maistro.runs.reconciliation import AttemptLifecycleReconciler

    reached, release, fenced = asyncio.Event(), asyncio.Event(), asyncio.Event()
    reclaimed: list[Any] = []
    transition_node = setup.owner.run_store.transition_node_run
    transition_run = setup.owner.run_store.transition_run

    async def gate(node_id: str, status: Any, **kwargs: Any) -> Any:
        if status is RunStatus.RUNNING:
            node = await setup.owner.run_store.get_node_run(node_id)
            if node.status is RunStatus.WAITING:
                reached.set()
                await release.wait()
        return await transition_node(node_id, status, **kwargs)

    async def fence(run_id: str, status: Any, **kwargs: Any) -> Any:
        result = await transition_run(run_id, status, **kwargs)
        if status is RunStatus.CANCELLED:
            fenced.set()
        return result

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("completions"):
            attempt = await setup.owner.run_store.get_attempt(
                current_execution_context().attempt_id
            )
            reclaimed.extend(
                await setup.owner.run_store.reclaim_expired_attempts(
                    now=attempt.execution_lease.expires_at + timedelta(seconds=1)
                )
            )
            await AttemptLifecycleReconciler(setup.owner.run_store).reconcile(reclaimed[0])
            raise httpx.ReadTimeout("fixture late failure", request=request)
        return httpx.Response(200, json={})

    setup.responder = respond
    monkeypatch.setattr(setup.owner.run_store, "transition_node_run", gate)
    monkeypatch.setattr(setup.owner.run_store, "transition_run", fence)
    task = asyncio.create_task(setup.activate())
    await asyncio.wait_for(reached.wait(), 2)
    task.cancel()
    await asyncio.wait_for(fenced.wait(), 2)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    (run,) = await setup.runs()
    (node,) = await setup.owner.run_store.list_node_runs(run.run_id)
    assert run.status is node.status is RunStatus.CANCELLED
    assert await setup.owner.run_store.get_attempt(reclaimed[0].attempt_id) == reclaimed[0]
    assert len(setup.requests) == 2 and setup.activated == []
