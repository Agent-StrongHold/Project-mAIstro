"""Persisted execution and configured authority, with only transport substituted."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from tests._admitted_model_fixture import setup

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.governed_invocation import InvocationDenied
from maistro.capabilities.providers.llm_gateway import ModelChatRequest
from maistro.credentials.router import CredentialScopeError
from maistro.graph.definitions import Graph, Node
from maistro.observability.correlation import bind_execution_context
from maistro.policy.types import Decision, PolicyVerdict
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import RunIntegrityError


def request() -> ModelChatRequest:
    return ModelChatRequest(
        model="request-alias",
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "inspect"}}],
        tool_choice="required",
        max_tokens=19,
        temperature=0.2,
    )


async def test_admitted_model_uses_persisted_actor_binding_and_scoped_credential() -> None:
    s = await setup()
    with bind_execution_context(
        run_id=s.identity[0], node_run_id=s.identity[1], attempt_id=s.identity[2]
    ):
        result = await s.calls.complete(request=request(), effect_key="turn-1")
    invocation = await s.effects.invocation_store.get(result.invocation_id)
    assert invocation.actor_id == "admitted-actor"
    assert invocation.binding.binding_id == "declared"
    assert invocation.binding.project_id == s.project_id
    assert invocation.run_id == s.identity[0]
    assert invocation.node_run_id == s.identity[1]
    assert invocation.attempt_id == s.identity[2]
    assert len(s.sent) == 1
    assert s.calls.gateway_base_url == "http://gateway.fixture"
    assert s.sent[0].headers["Authorization"] == "Bearer fixture-key"
    assert json.loads(s.sent[0].content)["tool_choice"] == "required"
    assert result.usage.input_units == 7
    assert result.usage.output_units == 3


@pytest.mark.parametrize("identity", [("", "", ""), ("run", "node", "attempt")])
async def test_missing_or_invented_execution_has_zero_effects(
    identity: tuple[str, str, str],
) -> None:
    s = await setup()
    with pytest.raises(RunIntegrityError):
        await s.calls.complete(request=request(), effect_key="turn-1", identity=identity)
    assert s.sent == []


@pytest.mark.parametrize("which", ["run", "node", "attempt"])
async def test_inactive_execution_has_zero_effects(which: str) -> None:
    s = await setup()
    if which == "run":
        await s.runs.transition_run(s.identity[0], RunStatus.CANCELLED)
    elif which == "node":
        await s.runs.transition_node_run(s.identity[1], RunStatus.CANCELLED)
    else:
        await s.runs.transition_attempt(
            s.identity[2], AttemptStatus.CANCELLED, fencing_token=s.fencing_token
        )
    with pytest.raises(RunIntegrityError):
        await s.calls.complete(request=request(), effect_key="turn-1", identity=s.identity)
    assert s.sent == []


@pytest.mark.parametrize(
    "context", [{"workspace_id": "foreign"}, {"project_id": "foreign"}, {"run_id": "foreign"}]
)
async def test_stale_context_cannot_replace_persisted_scope(context: dict[str, str]) -> None:
    s = await setup()
    with bind_execution_context(**context), pytest.raises(RunIntegrityError):
        await s.calls.complete(request=request(), effect_key="turn-1", identity=s.identity)
    assert s.sent == []


@pytest.mark.parametrize(
    "condition", ["unconfigured", "disabled", "revoked", "foreign", "undeclared", "ambiguous"]
)
async def test_binding_refusal_has_zero_effects(condition: str) -> None:
    s = await setup(bindings=condition != "unconfigured", disabled=condition == "disabled")
    binding_id = ""
    if condition == "revoked":
        await s.effects.bindings.revoke("declared")
    if condition in {"foreign", "undeclared", "ambiguous"}:
        binding = await s.effects.bindings.get("declared")
        values = {"binding_id": "other"}
        if condition == "foreign":
            values["workspace_id"] = "foreign"
        await s.effects.bindings.put(binding.model_copy(update=values))
        if condition == "ambiguous":
            s.calls._binding_ids = ("declared", "other")
        else:
            binding_id = "other"
            if condition == "foreign":
                s.calls._binding_ids = ("other",)
    with pytest.raises(BindingResolutionError):
        await s.calls.complete(
            request=request(), effect_key="turn-1", identity=s.identity, binding_id=binding_id
        )
    assert s.sent == []


async def test_missing_credential_cannot_be_fabricated_from_endpoint() -> None:
    s = await setup(key="")
    with pytest.raises(CredentialScopeError):
        await s.calls.complete(request=request(), effect_key="turn-1", identity=s.identity)
    assert s.sent == []


async def test_policy_denial_has_zero_effects() -> None:
    s = await setup()

    async def deny(*args: Any) -> PolicyVerdict:
        return PolicyVerdict(Decision.DENY, reason="fixture refusal", rule="fixture")

    s.calls._egress._effects = s.effects.with_policy_evaluator(deny)
    with pytest.raises(InvocationDenied):
        await s.calls.complete(request=request(), effect_key="turn-1", identity=s.identity)
    assert s.sent == []


async def test_unleased_fixture_is_not_production_admission() -> None:
    s = await setup(leased=False)
    with pytest.raises(RunIntegrityError, match="missing its execution lease"):
        await s.calls.complete(request=request(), effect_key="turn", identity=s.identity)
    assert s.sent == []


async def test_expired_attempt_lease_refuses_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import maistro.capabilities.admitted_model as adapter

    s = await setup()
    future = datetime.now(UTC) + timedelta(hours=1)

    class Clock:
        @staticmethod
        def now(tz: Any) -> datetime:
            return future

    monkeypatch.setattr(adapter, "datetime", Clock)
    with pytest.raises(RunIntegrityError, match="lease has expired"):
        await s.calls.complete(request=request(), effect_key="turn", identity=s.identity)
    assert s.sent == []


async def test_explicit_binding_selection_refuses_ambiguity_without_widening() -> None:
    s = await setup()
    binding = await s.effects.bindings.get("declared")
    await s.effects.bindings.put(binding.model_copy(update={"binding_id": "other"}))
    s.calls._binding_ids = ("declared", "other")
    result = await s.calls.complete(
        request=request(), effect_key="turn", identity=s.identity, binding_id="declared"
    )
    invocation = await s.effects.invocation_store.get(result.invocation_id)
    assert invocation.binding.binding_id == "declared"
    assert len(s.sent) == 1


async def test_completed_effect_replays_without_second_provider_call() -> None:
    s = await setup()
    first = await s.calls.complete(request=request(), effect_key="turn", identity=s.identity)
    second = await s.calls.complete(request=request(), effect_key="turn", identity=s.identity)
    assert second == first
    assert len(s.sent) == 1


@pytest.mark.parametrize("foreign", ["node", "attempt"])
async def test_records_cannot_be_spliced_between_persisted_executions(foreign: str) -> None:
    s = await setup()
    graph = Graph(
        name="other",
        workspace_id="workspace",
        project_id=s.project_id,
        nodes=[Node(node_id="chat", node_type="chat", name="chat")],
    )
    other_run = await s.runs.create_run(
        graph, actor_principal_id="other-actor", initial_status=RunStatus.QUEUED
    )
    await s.runs.transition_run(other_run.run_id, RunStatus.RUNNING)
    other_node = await s.runs.create_node_run(other_run.run_id, node_id="chat")
    for step in transition_path(other_node.status, RunStatus.RUNNING):
        other_node = await s.runs.transition_node_run(other_node.node_run_id, step)
    other_attempt = await s.runs.create_attempt(other_node.node_run_id, lease_holder="other-worker")
    await s.runs.transition_attempt(
        other_attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=other_attempt.execution_lease.fencing_token,
    )
    identity = (
        s.identity[0],
        other_node.node_run_id if foreign == "node" else s.identity[1],
        other_attempt.attempt_id,
    )
    with pytest.raises(RunIntegrityError, match="different executions"):
        await s.calls.complete(request=request(), effect_key="turn", identity=identity)
    assert s.sent == []


@pytest.mark.parametrize(
    "field,value", [("project_id", "foreign"), ("node_id", "foreign"), ("capability", "foreign")]
)
async def test_wrong_binding_scope_never_dispatches(field: str, value: str) -> None:
    s = await setup()
    binding = await s.effects.bindings.get("declared")
    await s.effects.bindings.put(binding.model_copy(update={"binding_id": "other", field: value}))
    s.calls._binding_ids = ("other",)
    with pytest.raises(BindingResolutionError):
        await s.calls.complete(request=request(), effect_key="turn", identity=s.identity)
    assert s.sent == []


async def test_live_adapter_resolves_revocation_again_before_replay() -> None:
    s = await setup()
    await s.calls.complete(request=request(), effect_key="turn", identity=s.identity)
    await s.effects.bindings.revoke("declared")
    with pytest.raises(BindingResolutionError):
        await s.calls.complete(request=request(), effect_key="turn", identity=s.identity)
    assert len(s.sent) == 1


async def test_stream_checks_admission_before_entering_provider() -> None:
    s = await setup(leased=False)
    with pytest.raises(RunIntegrityError, match="execution lease"):
        async for _ in s.calls.stream(request=request(), effect_key="turn", identity=s.identity):
            pytest.fail("unadmitted stream yielded a result")
    assert s.sent == []


async def test_closing_outer_adapter_deterministically_closes_inner_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await setup()
    closed = False

    async def chunks(**kwargs: Any):
        nonlocal closed
        assert kwargs["actor_id"] == "admitted-actor"
        assert kwargs["binding"].binding_id == "declared"
        try:
            yield {"choices": [{"delta": {"content": "first"}}]}
            pytest.fail("consumer already closed")
        finally:
            closed = True

    monkeypatch.setattr(s.calls._egress, "stream", chunks)
    stream = s.calls.stream(request=request(), effect_key="turn", identity=s.identity)
    assert (await anext(stream))["choices"][0]["delta"]["content"] == "first"
    await stream.aclose()
    assert closed


async def test_per_call_timeout_reaches_provider_transport() -> None:
    s = await setup()
    await s.calls.complete(
        request=request(), effect_key="turn", identity=s.identity, timeout_s=17.5
    )
    assert s.sent[0].extensions["timeout"] == {
        "connect": 17.5,
        "read": 17.5,
        "write": 17.5,
        "pool": 17.5,
    }


async def test_invalid_timeout_refuses_before_transport() -> None:
    s = await setup()
    with pytest.raises(ValueError, match="positive"):
        await s.calls.complete(
            request=request(), effect_key="turn", identity=s.identity, timeout_s=0
        )
    assert s.sent == []


async def test_pin_preflight_reads_configured_authority_without_dispatch() -> None:
    s = await setup()
    binding = await s.effects.bindings.get("declared")
    await s.effects.bindings.put(
        binding.model_copy(update={"binding_id": "pinned", "provider_name": "operator-pin"})
    )
    s.calls._binding_ids = ("pinned",)
    assert await s.calls.pinned_model(identity=s.identity) == "operator-pin"
    assert s.sent == []


@pytest.mark.parametrize("refusal", ["identity", "binding", "disabled", "credential"])
async def test_internal_setup_never_runs_before_execution_and_binding_authority(
    refusal: str,
) -> None:
    s = await setup(
        bindings=refusal != "binding",
        disabled=refusal == "disabled",
        key="" if refusal == "credential" else "fixture-key",
    )
    prepared: list[bool] = []

    async def prepare() -> None:
        prepared.append(True)

    with pytest.raises((RunIntegrityError, BindingResolutionError, CredentialScopeError)):
        await s.calls.complete(
            request=request(),
            effect_key="setup-check",
            identity=("absent", "absent", "absent") if refusal == "identity" else s.identity,
            setup=prepare,
        )
    assert prepared == [] and s.sent == []
