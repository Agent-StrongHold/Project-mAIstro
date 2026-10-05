"""Responses ingress and fallback retain canonical physical-call evidence."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite
import httpx
import pytest
from tests._admitted_model_fixture import Setup, setup

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.effect_context import binding_scope_policy, new_in_memory_effect_context
from maistro.capabilities.invocation import (
    InvocationStatus,
    ReconciliationDisposition,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.capabilities.providers.llm_gateway import (
    LlmAuthError,
    LlmHttpError,
    ModelChatRequest,
    UnsupportedModelIngress,
)
from maistro.capabilities.providers.model_stream_protocol import ModelStreamProtocolError
from maistro.http import override_transport
from maistro.runs.model import AttemptStatus
from maistro.runs.store import RunIntegrityError


def rejection(**changes: Any) -> dict[str, Any]:
    return {
        "error": {
            "type": "maistro.unsupported_ingress.v1",
            "ingress": "responses",
            "model": "request-alias",
            "dispatch": "not_started",
            "effect": "not_applied",
            **changes,
        }
    }


def response(**changes: Any) -> dict[str, Any]:
    return {
        "id": "resp-1",
        "model": "version-1",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "think"}]},
            {"type": "message", "content": [{"type": "output_text", "text": "answer"}]},
        ],
        "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
        **changes,
    }


def chat() -> dict[str, Any]:
    return {
        "model": "version-1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "answer"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }


def frame(event: Any) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


def stream_response() -> httpx.Response:
    return httpx.Response(
        200,
        content=b"".join(
            [
                frame({"type": "response.output_text.delta", "delta": "answer"}),
                frame({"type": "response.reasoning_summary_text.delta", "delta": "think"}),
                frame({"type": "response.output_text.done", "text": "answer"}),
                frame({"type": "response.completed", "response": response()}),
            ]
        ),
    )


def stream_chat() -> httpx.Response:
    return httpx.Response(
        200,
        content=frame(
            {"choices": [{"index": 0, "delta": {"content": "answer"}, "finish_reason": "stop"}]}
        )
        + frame({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
        + b"data: [DONE]\n\n",
    )


async def rows(s: Setup):
    return await s.effects.invocation_store.list_effect(
        run_id=s.identity[0], node_run_id=s.identity[1], binding_id="declared", effect_key="turn"
    )


async def call(s: Setup, *, streaming: bool = False, variant: str = "auto", **options: Any):
    request = ModelChatRequest(
        model="request-alias",
        api_variant=variant,
        messages=[{"role": "user", "content": "hi"}],
        **options,
    )
    if streaming:
        return [
            chunk
            async for chunk in s.calls.stream(
                request=request, effect_key="turn", identity=s.identity
            )
        ]
    return await s.calls.complete(request=request, effect_key="turn", identity=s.identity)


@pytest.mark.parametrize("streaming", [False, True])
async def test_responses_preserves_options_normalization_usage_and_replay(streaming: bool) -> None:
    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        return stream_response() if streaming else httpx.Response(200, json=response())

    with override_transport(httpx.MockTransport(handle)):
        result = await call(s, streaming=streaming, temperature=0.2, max_tokens=19)
        replay = await call(s, streaming=streaming)
    assert len(sent) == 1
    payload = json.loads(sent[0].content)
    assert sent[0].url.path == "/v1/responses"
    assert payload["temperature"] == 0.2 and payload["max_output_tokens"] == 19
    assert payload["input"] == [{"role": "user", "content": "hi"}]
    assert "stream_options" not in payload
    stored = (await rows(s))[0]
    assert stored.status is InvocationStatus.COMPLETED
    assert stored.usage.input_units == 7 and stored.usage.output_units == 3
    assert stored.result["choices"][0]["message"] == {
        "role": "assistant",
        "content": "answer",
        "reasoning_content": "think",
    }
    if streaming:
        assert result[0]["choices"][0]["delta"] == {"content": "answer"}
        assert replay[0]["_maistro_replayed"] is True
    else:
        assert result.body == replay.body == stored.result


@pytest.mark.parametrize("streaming", [False, True])
async def test_explicit_rejection_falls_back_once_as_two_invocations_and_replays(
    streaming: bool,
) -> None:
    s = await setup()
    sent = []

    async def handle(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(501, json=rejection())
        history = await rows(s)
        assert history[0].status is InvocationStatus.FAILED
        assert history[1].status is InvocationStatus.RUNNING
        assert history[0].effect_key == history[1].effect_key == "turn"
        assert (
            history[0].binding.provider_name == history[1].binding.provider_name == "request-alias"
        )
        return stream_chat() if streaming else httpx.Response(200, json=chat())

    with override_transport(httpx.MockTransport(handle)):
        await call(s, streaming=streaming)
        await call(s, streaming=streaming)
    assert [r.url.path for r in sent] == ["/v1/responses", "/v1/chat/completions"]
    history = await rows(s)
    assert [r.status for r in history] == [InvocationStatus.FAILED, InvocationStatus.COMPLETED]
    assert history[0].usage is None and history[1].usage.input_units == 7
    assert history[0].request.api_variant == "auto"
    assert history[1].request.api_variant == "chat_completions"


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "status,body",
    [(status, rejection()) for status in [400, 401, 403, 404, 405, 422, 429, 500, 503]]
    + [
        (501, body)
        for body in [
            {},
            {"error": "unsupported responses"},
            rejection(ingress="messages"),
            rejection(model="other"),
            rejection(dispatch="started"),
            rejection(effect="unknown"),
            rejection(type="unsupported_ingress"),
            rejection(extra="secret"),
        ]
    ],
)
async def test_ambiguous_errors_never_fall_back(streaming: bool, status: int, body: dict) -> None:
    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(status, json=body)

    with override_transport(httpx.MockTransport(handle)):
        with pytest.raises((LlmAuthError, LlmHttpError)):
            await call(s, streaming=streaming)
        with pytest.raises(UnsafeEffectRetry):
            await call(s, streaming=streaming)
    assert len(sent) == 1
    assert (await rows(s))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize("streaming", [False, True])
async def test_explicit_responses_refusal_is_failed_without_automatic_fallback(
    streaming: bool,
) -> None:
    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(501, json=rejection())

    with override_transport(httpx.MockTransport(handle)), pytest.raises(UnsupportedModelIngress):
        await call(s, streaming=streaming, variant="responses")
    assert len(sent) == 1 and (await rows(s))[0].status is InvocationStatus.FAILED


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("body", [b"", b"bad-json", b"x" * 4097, b'{"error": {}, "error": {}}'])
async def test_invalid_rejection_body_is_not_proof(body: bytes, streaming: bool) -> None:
    s = await setup()
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(501, content=body))),
        pytest.raises((LlmAuthError, LlmHttpError)),
    ):
        await call(s, streaming=streaming)
    assert (await rows(s))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize(
    "event",
    [
        {"type": "response.output_text.done", "text": "answer"},
        {"type": "response.failed"},
        {"type": "response.incomplete"},
        {"type": "response.completed"},
        {"type": "response.completed", "response": response(status="in_progress")},
        {"type": "response.completed", "response": response(output=[])},
        {"error": rejection()["error"]},
    ],
)
async def test_partial_or_failed_responses_are_unknown(event: dict) -> None:
    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(
            200,
            content=frame({"type": "response.output_text.delta", "delta": "partial"})
            + frame(event),
        )

    with override_transport(httpx.MockTransport(handle)), pytest.raises(ModelStreamProtocolError):
        await call(s, streaming=True)
    assert len(sent) == 1 and (await rows(s))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize("change", ["revoked", "cancelled"])
async def test_fallback_revalidates_binding_and_execution(change: str) -> None:
    s = await setup()
    sent = []

    async def handle(request):
        sent.append(request)
        if change == "revoked":
            await s.effects.bindings.revoke("declared")
        else:
            await s.runs.transition_attempt(
                s.identity[2], AttemptStatus.CANCELLED, fencing_token=s.fencing_token
            )
        return httpx.Response(501, json=rejection())

    with (
        override_transport(httpx.MockTransport(handle)),
        pytest.raises((BindingResolutionError, RunIntegrityError)),
    ):
        await call(s)
    assert len(sent) == 1 and (await rows(s))[0].status is InvocationStatus.FAILED


async def test_setup_rejection_stays_unknown_and_setup_does_not_repeat() -> None:
    s = await setup()
    prepared = []

    async def prepare():
        prepared.append(True)

    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(501, json=rejection()))),
        pytest.raises(RuntimeError),
    ):
        await s.calls.complete(
            request=ModelChatRequest(model="request-alias", api_variant="auto"),
            effect_key="turn",
            identity=s.identity,
            setup=prepare,
        )
    assert prepared == [True]
    assert (await rows(s))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize(
    "disposition", [ReconciliationDisposition.NOT_APPLIED, ReconciliationDisposition.INDETERMINATE]
)
async def test_sqlite_reconciliation_preserves_normal_reattempt_contract(
    tmp_path, disposition
) -> None:
    async with aiosqlite.connect(tmp_path / "effects.sqlite") as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        effects = new_in_memory_effect_context(
            policy_evaluator=binding_scope_policy, invocation_store=store
        )
        s = await setup(effects=effects)
        sent = []

        def handle(request):
            sent.append(request)
            return httpx.Response(500) if len(sent) == 1 else httpx.Response(200, json=response())

        with override_transport(httpx.MockTransport(handle)):
            with pytest.raises(RuntimeError):
                await call(s)
            first = (await rows(s))[0]
            await s.effects.invocations.reconcile(
                first.invocation_id,
                disposition=disposition,
                source="gateway-receipt",
                actor="operator",
                reason="checked gateway dispatch record",
                evidence={"dispatch_record": "fixture"},
                workspace_id="workspace",
                project_id=s.project_id,
            )
            if disposition is ReconciliationDisposition.NOT_APPLIED:
                await call(s)
                assert len(sent) == 2 and (await rows(s))[-1].status is InvocationStatus.COMPLETED
            else:
                with pytest.raises(UnsafeEffectRetry):
                    await call(s)
                assert len(sent) == 1 and (await rows(s))[-1].status is InvocationStatus.UNKNOWN


class _Quota:
    def __init__(self, *, deny_second: bool) -> None:
        self.reservations = []
        self.charged = set()
        self.deny_second = deny_second

    async def reserve(self, invocation, binding):
        self.reservations.append(invocation.invocation_id)
        if self.deny_second and len(self.reservations) == 2:
            raise PermissionError("quota denied")

    async def observe(self, invocation):
        if invocation.status is InvocationStatus.COMPLETED:
            self.charged.add(invocation.invocation_id)


@pytest.mark.parametrize("deny_second", [False, True])
async def test_fallback_reserves_again_and_replay_does_not_charge_twice(deny_second: bool) -> None:
    quota = _Quota(deny_second=deny_second)
    s = await setup(
        effects=new_in_memory_effect_context(policy_evaluator=binding_scope_policy, quota=quota)
    )
    sent = []

    def handle(request):
        sent.append(request)
        return (
            httpx.Response(501, json=rejection())
            if len(sent) == 1
            else httpx.Response(200, json=chat())
        )

    with override_transport(httpx.MockTransport(handle)):
        if deny_second:
            with pytest.raises(PermissionError, match="quota denied"):
                await call(s)
            assert len(sent) == 1 and not quota.charged
        else:
            await call(s)
            await call(s)
            assert len(sent) == 2 and len(quota.charged) == 1
    assert len(quota.reservations) == 2


@pytest.mark.parametrize("variant", ["auto", "responses", "chat_completions"])
async def test_tool_calls_stay_on_chat_with_sampling_and_format_options(variant: str) -> None:
    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(200, json=chat())

    tools = [{"type": "function", "function": {"name": "inspect"}}]
    with override_transport(httpx.MockTransport(handle)):
        await call(
            s,
            variant=variant,
            tools=tools,
            tool_choice="required",
            response_format={"type": "json_object"},
            temperature=None,
        )
    body = json.loads(sent[0].content)
    assert sent[0].url.path == "/v1/chat/completions"
    assert body["tools"] == tools and body["tool_choice"] == "required"
    assert body["response_format"] == {"type": "json_object"} and "temperature" not in body


@pytest.mark.parametrize("streaming", [False, True])
async def test_connection_failure_is_retryable_without_being_unsupported(streaming: bool) -> None:
    from maistro.capabilities.invocation import EffectNotApplied

    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        if len(sent) == 1:
            raise httpx.ConnectTimeout("connection not established")
        return stream_response() if streaming else httpx.Response(200, json=response())

    with override_transport(httpx.MockTransport(handle)):
        with pytest.raises(EffectNotApplied):
            await call(s, streaming=streaming)
        assert len(sent) == 1
        await call(s, streaming=streaming)
    assert [r.url.path for r in sent] == ["/v1/responses", "/v1/responses"]


@pytest.mark.parametrize(
    "supported,variant,tools,expected",
    [
        (None, "auto", None, "/v1/responses"),
        (("chat_completions",), "auto", None, "/v1/chat/completions"),
        (("chat_completions", "responses"), "auto", None, "/v1/responses"),
        (("responses",), "responses", None, "/v1/responses"),
        (("chat_completions",), "responses", None, None),
        (("responses",), "chat_completions", None, None),
        (("responses",), "auto", [{"type": "function"}], None),
    ],
)
async def test_declared_ingresses_select_before_http_or_refuse(
    supported, variant, tools, expected
) -> None:
    from maistro.capabilities.invocation import EffectNotApplied
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.types import ModelMetadata

    metadata = ModelMetadata(
        name="request-alias",
        provider="vendor",
        cost_per_1k_input=1,
        cost_per_1k_output=1,
        latency_p50_ms=1,
        supported_ingresses=supported,
    )
    s = await setup(registry=InMemoryProviderRegistry(models=[metadata]))
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(
            200, json=response() if request.url.path.endswith("responses") else chat()
        )

    with override_transport(httpx.MockTransport(handle)):
        if expected is None:
            with pytest.raises(EffectNotApplied):
                await call(s, variant=variant, tools=tools)
            assert sent == [] and (await rows(s))[0].status is InvocationStatus.FAILED
        else:
            await call(s, variant=variant, tools=tools)
            assert len(sent) == 1 and sent[0].url.path == expected


@pytest.mark.parametrize(
    "declaration",
    [[], ["responses", "responses"], ["messages"], ["interactions"], "responses", [1], [{}]],
)
async def test_config_rejects_malformed_ingress_declarations(tmp_path, declaration) -> None:
    import yaml

    from maistro.providers.config import load_provider_config
    from maistro.providers.errors import ProviderConfigError

    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "name": "model",
                        "provider": "vendor",
                        "cost_input": 1,
                        "cost_output": 1,
                        "latency_p50_ms": 1,
                        "supported_ingresses": declaration,
                    }
                ]
            }
        )
    )
    with pytest.raises(ProviderConfigError):
        load_provider_config(path)


@pytest.mark.parametrize(
    "declaration", [None, ["chat_completions"], ["responses", "chat_completions"]]
)
async def test_config_loads_explicit_ingress_evidence(tmp_path, declaration) -> None:
    import yaml

    from maistro.providers.config import load_provider_config

    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "name": "model",
                        "provider": "vendor",
                        "cost_input": 1,
                        "cost_output": 1,
                        "latency_p50_ms": 1,
                        "supported_ingresses": declaration,
                    }
                ]
            }
        )
    )
    models, _ = load_provider_config(path)
    assert models[0].supported_ingresses == (
        tuple(declaration) if declaration is not None else None
    )


@pytest.mark.parametrize(
    "output",
    [
        None,
        [None],
        [{"type": "function_call"}],
        [{"type": "message", "content": None}],
        [{"type": "message", "content": [{"type": "output_text", "text": None}]}],
    ],
)
async def test_malformed_completed_response_is_unknown(output) -> None:
    s = await setup()
    with (
        override_transport(
            httpx.MockTransport(lambda _: httpx.Response(200, json=response(output=output)))
        ),
        pytest.raises(ModelStreamProtocolError),
    ):
        await call(s)
    assert (await rows(s))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": True, "output_tokens": 3},
        {"input_tokens": -1, "output_tokens": 3},
    ],
)
async def test_missing_or_invalid_usage_is_not_fabricated(usage) -> None:
    s = await setup()
    with override_transport(
        httpx.MockTransport(lambda _: httpx.Response(200, json=response(usage=usage)))
    ):
        await call(s)
    stored = (await rows(s))[0]
    assert stored.status is InvocationStatus.COMPLETED
    assert stored.usage is None and "usage" not in stored.result


@pytest.mark.parametrize(
    "format_",
    [
        {"type": "json_object"},
        {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": {"type": "object"}, "strict": True},
        },
    ],
)
async def test_responses_structured_format_and_unspecified_temperature_are_preserved(
    format_,
) -> None:
    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(200, json=response())

    with override_transport(httpx.MockTransport(handle)):
        await call(s, response_format=format_, temperature=None)
    payload = json.loads(sent[0].content)
    assert "temperature" not in payload
    assert payload["text"]["format"] == (
        {**format_["json_schema"], "type": "json_schema"} if "json_schema" in format_ else format_
    )


async def test_completion_event_alone_delivers_actual_text_and_reasoning() -> None:
    s = await setup()
    data = frame({"type": "response.created"}) + frame(
        {"type": "response.completed", "response": response()}
    )
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, content=data))):
        chunks = await call(s, streaming=True)
    assert chunks[0]["choices"][0]["delta"] == {"content": "answer", "reasoning_content": "think"}


@pytest.mark.parametrize(
    "data",
    [
        b"data: [DONE]\n\n",
        frame({"type": "response.output_text.delta", "delta": 1}),
        frame({}),
        frame({"type": "response.reasoning_text.delta", "delta": "think"}),
    ],
)
async def test_unfinished_responses_stream_never_completes(data: bytes) -> None:
    s = await setup()
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(200, content=data))),
        pytest.raises(ModelStreamProtocolError),
    ):
        await call(s, streaming=True)
    assert (await rows(s))[0].status is InvocationStatus.UNKNOWN


async def test_router_selected_model_cannot_change_during_protocol_fallback() -> None:
    from maistro.capabilities.invocation import CapabilityUnavailable
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.types import ModelMetadata

    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name=name,
                provider="vendor",
                cost_per_1k_input=cost,
                cost_per_1k_output=cost,
                latency_p50_ms=1,
            )
            for name, cost in [("first", 1), ("second", 2)]
        ]
    )
    s = await setup(registry=registry)
    sent = []

    def handle(request):
        sent.append(request)
        registry.mark_unavailable("first")
        return httpx.Response(501, json=rejection(model="first"))

    with override_transport(httpx.MockTransport(handle)), pytest.raises(CapabilityUnavailable):
        await s.calls.complete(
            request=ModelChatRequest(api_variant="auto"), effect_key="turn", identity=s.identity
        )
    assert len(sent) == 1
    assert json.loads(sent[0].content)["model"] == "first"
    assert (await rows(s))[0].status is InvocationStatus.FAILED


async def test_responses_close_cancels_and_closes_transport_without_fallback() -> None:
    from collections.abc import AsyncIterator

    class Source(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(20):
                yield frame({"type": "response.output_text.delta", "delta": "x"})

        async def aclose(self):
            self.closed = True

    source = Source()
    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(200, stream=source)

    with override_transport(httpx.MockTransport(handle)):
        stream = s.calls.stream(
            request=ModelChatRequest(model="request-alias", api_variant="auto"),
            effect_key="turn",
            identity=s.identity,
        )
        await anext(stream)
        await stream.aclose()
    assert source.closed and len(sent) == 1
    assert (await rows(s))[0].status is InvocationStatus.UNKNOWN


async def test_fallback_rechecks_policy_after_rejected_physical_call() -> None:
    from maistro.capabilities.governed_invocation import InvocationDenied
    from maistro.policy.types import Decision, PolicyVerdict

    sent = []

    async def policy(*_):
        return PolicyVerdict(
            Decision.DENY if sent else Decision.ALLOW, reason="fixture", rule="fixture"
        )

    s = await setup(effects=new_in_memory_effect_context(policy_evaluator=policy))

    def handle(request):
        sent.append(request)
        return httpx.Response(501, json=rejection())

    with override_transport(httpx.MockTransport(handle)), pytest.raises(InvocationDenied):
        await call(s)
    assert len(sent) == 1 and len(await rows(s)) == 1


async def test_fallback_rechecks_expired_execution_lease(monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    from maistro.capabilities import admitted_model

    s = await setup()
    future = datetime.now(UTC) + timedelta(hours=1)

    class Clock:
        @staticmethod
        def now(_):
            return future

    sent = []

    def handle(request):
        sent.append(request)
        monkeypatch.setattr(admitted_model, "datetime", Clock)
        return httpx.Response(501, json=rejection())

    with (
        override_transport(httpx.MockTransport(handle)),
        pytest.raises(RunIntegrityError, match="expired"),
    ):
        await call(s)
    assert len(sent) == 1 and (await rows(s))[0].status is InvocationStatus.FAILED


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("with_delta", [False, True])
async def test_completed_refusal_remains_visible_and_known_completed(
    streaming: bool, with_delta: bool
) -> None:
    s = await setup()
    body = response(
        output=[
            {
                "type": "message",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "I cannot help with that."}],
            }
        ],
        error=None,
        incomplete_details=None,
    )
    data = (
        frame({"type": "response.refusal.delta", "delta": "I cannot help with that."})
        if with_delta
        else b""
    )
    data += frame({"type": "response.completed", "response": body})
    with override_transport(
        httpx.MockTransport(
            lambda _: (
                httpx.Response(200, content=data) if streaming else httpx.Response(200, json=body)
            )
        )
    ):
        await call(s, streaming=streaming)
    stored = (await rows(s))[0]
    assert stored.status is InvocationStatus.COMPLETED
    message = stored.result["choices"][0]["message"]
    assert message["content"] == message["refusal"] == "I cannot help with that."


@pytest.mark.parametrize(
    "channels", [("reasoning",), ("summary",), ("reasoning", "summary"), ("summary", "reasoning")]
)
async def test_reasoning_native_channels_match_their_own_final_fields(
    channels: tuple[str, ...],
) -> None:
    s = await setup()
    item: dict[str, Any] = {"type": "reasoning", "summary": []}
    if "reasoning" in channels:
        item["content"] = [{"type": "reasoning_text", "text": "raw"}]
    if "summary" in channels:
        item["summary"] = [{"type": "summary_text", "text": "summary"}]
    events = [
        {
            "type": "response.reasoning_text.delta"
            if channel == "reasoning"
            else "response.reasoning_summary_text.delta",
            "delta": "raw" if channel == "reasoning" else "summary",
        }
        for channel in channels
    ]
    events.append({"type": "response.completed", "response": response(output=[item])})
    with override_transport(
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"".join(map(frame, events))))
    ):
        chunks = await call(s, streaming=True)
    expected = "".join("raw" if channel == "reasoning" else "summary" for channel in channels)
    assert (
        "".join(chunk["choices"][0]["delta"].get("reasoning_content", "") for chunk in chunks)
        == expected
    )
    assert (await rows(s))[0].result["choices"][0]["message"]["reasoning_content"] == expected


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "contradiction",
    [{"error": {"code": "server_error"}}, {"incomplete_details": {"reason": "max_output_tokens"}}],
)
async def test_completed_status_cannot_override_error_or_incomplete_evidence(
    streaming: bool, contradiction: dict
) -> None:
    s = await setup()
    body = response(**contradiction)
    data = frame({"type": "response.completed", "response": body})
    with (
        override_transport(
            httpx.MockTransport(
                lambda _: (
                    httpx.Response(200, content=data)
                    if streaming
                    else httpx.Response(200, json=body)
                )
            )
        ),
        pytest.raises(ModelStreamProtocolError),
    ):
        await call(s, streaming=streaming)
    assert (await rows(s))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize(
    "item",
    [
        {"type": "reasoning", "summary": None},
        {"type": "reasoning", "summary": [{"type": "reasoning_text", "text": "wrong channel"}]},
        {"type": "reasoning", "content": [{"type": "reasoning_text", "text": 1}]},
        {"type": "reasoning", "content": {}},
        {"type": "message", "status": "incomplete", "content": []},
        {"type": "message", "content": [{"type": "audio", "text": "unsupported"}]},
    ],
)
async def test_native_output_shapes_are_validated(item: dict) -> None:
    s = await setup()
    with (
        override_transport(
            httpx.MockTransport(lambda _: httpx.Response(200, json=response(output=[item])))
        ),
        pytest.raises(ModelStreamProtocolError),
    ):
        await call(s)
    assert (await rows(s))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize("streaming", [False, True])
async def test_failed_chat_alternate_is_unknown_and_never_recurses(streaming: bool) -> None:
    s = await setup()
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(501, json=rejection())

    with override_transport(httpx.MockTransport(handle)):
        with pytest.raises(LlmHttpError):
            await call(s, streaming=streaming)
        with pytest.raises(UnsafeEffectRetry):
            await call(s, streaming=streaming)
    assert [request.url.path for request in sent] == ["/v1/responses", "/v1/chat/completions"]
    assert [row.status for row in await rows(s)] == [
        InvocationStatus.FAILED,
        InvocationStatus.UNKNOWN,
    ]


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("lane", ["chat_completions", "responses"])
async def test_provider_ingress_evidence_overrides_spoof_and_survives_metadata_change(
    streaming: bool,
    lane: str,
) -> None:
    from dataclasses import replace

    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.types import ModelMetadata

    other = "responses" if lane == "chat_completions" else "chat_completions"
    metadata = ModelMetadata(
        name="request-alias",
        provider="vendor",
        cost_per_1k_input=1,
        cost_per_1k_output=1,
        latency_p50_ms=1,
        supported_ingresses=(lane,),
    )
    registry = InMemoryProviderRegistry(models=[metadata])
    s = await setup(registry=registry)
    sent = []
    body = response() if lane == "responses" else chat()
    body["_maistro_ingress"] = other
    if lane == "responses":
        data = frame({"type": "response.completed", "response": body, "_maistro_ingress": other})
    else:
        data = frame(
            {
                "choices": [{"index": 0, "delta": {"content": "answer"}, "finish_reason": "stop"}],
                "_maistro_ingress": other,
            }
        )
        data += frame({"choices": [], "usage": body["usage"]}) + b"data: [DONE]\n\n"

    def handle(request):
        sent.append(request)
        return httpx.Response(200, content=data) if streaming else httpx.Response(200, json=body)

    with override_transport(httpx.MockTransport(handle)):
        original = await call(s, streaming=streaming)
        stored = (await rows(s))[0]
        assert stored.result["_maistro_ingress"] == lane
        assert stored.usage.input_units == 7 and stored.usage.output_units == 3
        registry.register_model(replace(metadata, supported_ingresses=(other,)))
        replay = await call(s, streaming=streaming)
    assert len(sent) == 1
    assert sent[0].url.path == ("/v1/responses" if lane == "responses" else "/v1/chat/completions")
    assert (await rows(s))[0].result == stored.result
    if streaming:
        assert replay[0]["_maistro_replayed"] is True
        assert replay[0]["_maistro_ingress"] == lane
        assert all(chunk.get("_maistro_ingress", lane) == lane for chunk in original)
    else:
        assert original.body["_maistro_ingress"] == replay.body["_maistro_ingress"] == lane


@pytest.mark.parametrize("streaming", [False, True])
async def test_unknown_outcome_does_not_claim_completed_ingress_evidence(streaming: bool) -> None:
    s = await setup()

    def handle(request):
        raise httpx.ReadTimeout("outcome unknown", request=request)

    with override_transport(httpx.MockTransport(handle)), pytest.raises(httpx.ReadTimeout):
        await call(s, streaming=streaming)
    stored = (await rows(s))[0]
    assert stored.status is InvocationStatus.UNKNOWN
    assert stored.result is None
