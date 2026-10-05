"""Agent-shaped calls join canonical admission without manufacturing authority."""

from __future__ import annotations

import json

import httpx
import pytest
from tests._admitted_model_fixture import Setup, setup

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.model_chat import GovernedLLMClient
from maistro.http import set_test_transport
from maistro.observability.correlation import bind_execution_context
from maistro.runs.store import RunIntegrityError

from .test_model_chat_streaming import _Bytes, _chunk, _frame


def client(s: Setup) -> GovernedLLMClient:
    return GovernedLLMClient(s.calls)


def context(s: Setup):
    return bind_execution_context(
        run_id=s.identity[0], node_run_id=s.identity[1], attempt_id=s.identity[2]
    )


async def rows(s: Setup, effect_key: str = "agent-llm-1"):
    return await s.effects.invocation_store.list_effect(
        run_id=s.identity[0],
        node_run_id=s.identity[1],
        binding_id="declared",
        effect_key=effect_key,
    )


async def test_agent_client_joins_persisted_actor_and_configured_binding() -> None:
    s = await setup()
    llm = client(s)
    with context(s):
        result = await llm.complete([{"role": "user", "content": "hello"}], "request-alias")
    assert result["choices"][0]["message"]["content"] == "answer"
    (invocation,) = await rows(s)
    assert invocation.actor_id == "admitted-actor"
    assert invocation.binding.project_id == s.project_id
    assert invocation.attempt_id == s.identity[2]
    assert invocation.usage.input_units == 7
    assert invocation.usage.output_units == 3
    assert len(s.sent) == 1


async def test_agent_client_refuses_revoked_binding_instead_of_creating_one() -> None:
    s = await setup()
    llm = client(s)
    await s.effects.bindings.revoke("declared")
    with context(s), pytest.raises(BindingResolutionError):
        await llm.complete([], "request-alias")
    assert s.sent == []


async def test_agent_client_refuses_complete_but_invented_correlation() -> None:
    s = await setup()
    llm = client(s)
    with (
        bind_execution_context(run_id="invented", node_run_id="invented", attempt_id="invented"),
        pytest.raises(RunIntegrityError),
    ):
        await llm.complete([], "request-alias")
    assert s.sent == []


async def test_agent_stream_is_incremental_with_admitted_actor_and_usage() -> None:
    s = await setup()
    llm = client(s)
    source = _Bytes(
        [
            *[_frame(_chunk(str(i))) for i in range(8)],
            _frame(_chunk(finish="stop")),
            _frame({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}),
            b"data: [DONE]\n\n",
        ]
    )

    def transport(request: httpx.Request) -> httpx.Response:
        s.sent.append(request)
        return httpx.Response(200, stream=source)

    set_test_transport(httpx.MockTransport(transport))
    with context(s):
        stream = llm.stream([], "request-alias", tool_choice="required")
        assert (await anext(stream))["choices"][0]["delta"]["content"] == "0"
        assert not source.finished.is_set()
        assert (await rows(s))[0].actor_id == "admitted-actor"
        assert (await rows(s))[0].status is InvocationStatus.RUNNING
        rest = [chunk async for chunk in stream]
    assert len(rest) == 9
    assert source.closed
    (invocation,) = await rows(s)
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.usage.input_units == 7
    assert invocation.usage.output_units == 3
    assert json.loads(s.sent[0].content)["tool_choice"] == "required"
    assert len(s.sent) == 1


@pytest.mark.parametrize("mode", ["complete", "stream"])
@pytest.mark.parametrize(
    "condition", ["unconfigured", "disabled", "ambiguous", "foreign", "credential"]
)
async def test_agent_admission_refusal_never_falls_back(mode: str, condition: str) -> None:
    s = await setup(
        bindings=condition != "unconfigured",
        disabled=condition == "disabled",
        key="" if condition == "credential" else "fixture-key",
    )
    if condition in {"ambiguous", "foreign"}:
        binding = await s.effects.bindings.get("declared")
        replacement = {"binding_id": "other"}
        if condition == "foreign":
            replacement["project_id"] = "foreign-project"
        await s.effects.bindings.put(binding.model_copy(update=replacement))
        s.calls._binding_ids = ("declared", "other") if condition == "ambiguous" else ("other",)
    llm = client(s)
    from maistro.credentials.router import CredentialScopeError

    error = CredentialScopeError if condition == "credential" else BindingResolutionError
    with context(s), pytest.raises(error):
        if mode == "complete":
            await llm.complete([], "request-alias")
        else:
            await anext(llm.stream([], "request-alias"))
    assert s.sent == []
    assert await rows(s) == []


async def test_agent_stream_close_settles_unknown_without_fallback() -> None:
    s = await setup()
    llm = client(s)
    source = _Bytes([_frame(_chunk(str(i))) for i in range(12)])

    def transport(request: httpx.Request) -> httpx.Response:
        s.sent.append(request)
        return httpx.Response(200, stream=source)

    set_test_transport(httpx.MockTransport(transport))
    with context(s):
        stream = llm.stream([], "request-alias")
        await anext(stream)
        await stream.aclose()
        assert (await rows(s))[0].status is InvocationStatus.UNKNOWN
        assert source.closed
    assert len(s.sent) == 1


async def test_agent_stream_stale_turn_refuses_until_explicit_reset() -> None:
    s = await setup()
    llm = client(s)
    with context(s):
        llm.set_turn()
    with bind_execution_context(run_id="other", node_run_id="other", attempt_id="other"):
        with pytest.raises(RunIntegrityError, match="does not match the stored turn"):
            await anext(llm.stream([], "request-alias"))
        assert llm._turn.get() is None
        assert llm._sequence.get() == 0
    assert s.sent == []


async def test_agent_stream_without_execution_refuses_without_effect() -> None:
    from maistro.observability.correlation import detached_execution_context

    s = await setup()
    with detached_execution_context(), pytest.raises(RunIntegrityError):
        await anext(client(s).stream([], "request-alias"))
    assert s.sent == []


async def test_agent_client_replay_rechecks_binding_revocation() -> None:
    s = await setup()
    llm = client(s)
    with context(s):
        first = await llm.complete([], "request-alias")
        llm.set_turn()
        assert await llm.complete([], "request-alias") == first
        assert len(s.sent) == 1
        await s.effects.bindings.revoke("declared")
        llm.set_turn()
        with pytest.raises(BindingResolutionError):
            await llm.complete([], "request-alias")
    assert len(s.sent) == 1
    assert len(await rows(s)) == 1
