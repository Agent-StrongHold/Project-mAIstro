"""Incremental gateway streaming still has one canonical Invocation owner."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
import httpx
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    Invocation,
    InvocationQuota,
    InvocationStatus,
    InvocationStore,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.capabilities.model_chat import ModelChatEgress, ModelChatRequest
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint, LlmAuthError, LlmHttpError
from maistro.capabilities.providers.model_stream_protocol import (
    ChatStreamAccumulator,
    ModelStreamProtocolError,
)
from maistro.credentials.types import CredentialRecord
from maistro.http import override_transport
from maistro.policy.types import Decision, PolicyVerdict
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata
from maistro.quota.usage_log import InMemoryUsageLog


def _frame(chunk: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(chunk)}\n\n".encode()


def _chunk(content: str = "", *, finish: str | None = None, **delta: Any) -> dict[str, Any]:
    return {
        "id": "chat-1",
        "model": "model-version",
        "choices": [{"index": 0, "delta": {"content": content, **delta}, "finish_reason": finish}],
    }


class _Bytes(httpx.AsyncByteStream):
    def __init__(self, frames: list[bytes | Exception]) -> None:
        self.frames = frames
        self.read = 0
        self.closed = False
        self.close_count = 0
        self.finished = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for frame in self.frames:
            self.read += 1
            if isinstance(frame, Exception):
                raise frame
            yield frame
        self.finished.set()

    async def aclose(self) -> None:
        self.closed = True
        self.close_count += 1


def _fixture(
    store: InvocationStore | None = None,
    quota: InvocationQuota | None = None,
) -> tuple[CapabilityEffectContext, ModelChatEgress, dict[str, Any]]:
    effects = new_in_memory_effect_context(
        policy_evaluator=binding_scope_policy,
        invocation_store=store,
        usage_log=InMemoryUsageLog(),
        quota=quota,
    )
    effects.credentials.add(
        workspace_id="ws",
        project_id="project",
        record=CredentialRecord(key_id="key", provider="litellm", api_key="scoped-secret"),
    )
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="model",
                provider="vendor",
                cost_per_1k_input=1.0,
                cost_per_1k_output=2.0,
                latency_p50_ms=10,
            )
        ]
    )
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="https://gateway.invalid", api_key="never-use"),
    )
    arguments = {
        "binding": Binding(
            binding_id="stream-binding",
            workspace_id="ws",
            project_id="project",
            capability="model.chat",
            credential_refs=("key",),
        ),
        "run_id": "run",
        "node_run_id": "node-run",
        "attempt_id": "attempt",
        "effect_key": "model-1",
        "request": ModelChatRequest(model="model", messages=[{"role": "user", "content": "hi"}]),
    }
    return effects, egress, arguments


async def _rows(effects: CapabilityEffectContext) -> list[Invocation]:
    return await effects.invocation_store.list_effect(
        run_id="run",
        node_run_id="node-run",
        binding_id="stream-binding",
        effect_key="model-1",
    )


async def test_first_chunk_precedes_completion_and_applies_bounded_backpressure() -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes(
        [
            *[_frame(_chunk(str(i))) for i in range(12)],
            _frame(_chunk(finish="stop")),
            b"data: [DONE]\n\n",
        ]
    )
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=source)

    with override_transport(httpx.MockTransport(handle)):
        stream = egress.stream(**arguments)
        first = await anext(stream)
        assert first["choices"][0]["delta"]["content"] == "0"
        assert not source.finished.is_set()
        assert (await _rows(effects))[0].status is InvocationStatus.RUNNING
        # Let producer run until its bounded delivery queue blocks.
        for _ in range(4):
            await asyncio.sleep(0)
        assert source.read <= 3
        rest = [chunk async for chunk in stream]
    assert len(rest) == 12
    assert source.closed
    assert (await _rows(effects))[0].status is InvocationStatus.COMPLETED
    payload = json.loads(requests[0].content)
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert requests[0].headers["Authorization"] == "Bearer scoped-secret"


async def test_stream_preserves_deltas_usage_and_replays_without_dispatch() -> None:
    effects, egress, arguments = _fixture()
    chunks = [
        _chunk(
            "Hi",
            reasoning_content="think",
            tool_calls=[
                {
                    "index": 0,
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "look", "arguments": '{"a":'},
                }
            ],
        ),
        _chunk("!", tool_calls=[{"index": 0, "function": {"arguments": "1}"}}]),
        _chunk(finish="tool_calls"),
        {
            "model": "model-version",
            "choices": [],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        },
    ]
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=_Bytes([*map(_frame, chunks), b"data: [DONE]\n\n"]))

    with override_transport(httpx.MockTransport(handle)):
        actual = [chunk async for chunk in egress.stream(**arguments)]
        replay = [chunk async for chunk in egress.stream(**arguments)]
    assert actual == chunks
    assert len(requests) == 1
    assert len(replay) == 1 and replay[0]["_maistro_replayed"] is True
    stored = (await _rows(effects))[0]
    assert stored.usage is not None
    assert stored.usage.input_units == 8
    assert stored.usage.output_units == 3
    assert stored.usage.model_version == "model-version"
    assert isinstance(stored.result, dict)
    message = stored.result["choices"][0]["message"]
    assert message["content"] == "Hi!"
    assert message["reasoning_content"] == "think"
    assert message["tool_calls"][0]["function"] == {"name": "look", "arguments": '{"a":1}'}
    assert replay[0]["choices"][0]["delta"] == message
    events = effects.usage_log.events_for("model")
    assert len(events) == 1
    assert events[0].invocation_id == stored.invocation_id
    assert (events[0].input_tokens, events[0].output_tokens) == (8, 3)
    assert events[0].usage_reported is True


@pytest.mark.parametrize(
    "ending",
    [b"", b"data: [DONE]\n\n", b"data: broken\n\n", b'data: {"error":{"message":"failed"}}\n\n'],
)
async def test_incomplete_or_invalid_stream_is_unknown_and_not_retryable(ending: bytes) -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes([_frame(_chunk("partial")), ending])
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))):
        with pytest.raises(RuntimeError):
            _ = [chunk async for chunk in egress.stream(**arguments)]
        assert (await _rows(effects))[0].status is InvocationStatus.UNKNOWN
        with pytest.raises(UnsafeEffectRetry):
            _ = [chunk async for chunk in egress.stream(**arguments)]
    assert source.closed


async def test_explicit_close_cancels_producer_and_records_unknown() -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes(
        [
            *[_frame(_chunk(str(i))) for i in range(20)],
            _frame(_chunk(finish="stop")),
            b"data: [DONE]\n\n",
        ]
    )
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))):
        stream = egress.stream(**arguments)
        await anext(stream)
        await stream.aclose()
    assert source.closed
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.UNKNOWN
    assert row.dispatch_active is False
    assert row.usage is None


async def test_connect_failure_is_proven_failed() -> None:
    effects, egress, arguments = _fixture()

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    with override_transport(httpx.MockTransport(fail)), pytest.raises(EffectNotApplied):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    assert (await _rows(effects))[0].status is InvocationStatus.FAILED


async def test_policy_denial_never_dispatches() -> None:
    effects, egress, arguments = _fixture()

    async def deny(*_: Any) -> PolicyVerdict:
        return PolicyVerdict(Decision.DENY, reason="denied", rule="test")

    egress._effects = effects.with_policy_evaluator(deny)

    def unexpected(_: httpx.Request) -> httpx.Response:
        pytest.fail("denied request dispatched")

    with override_transport(httpx.MockTransport(unexpected)), pytest.raises(PermissionError):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    assert await _rows(effects) == []


class _BlockedBytes(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.reading = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield _frame(_chunk("partial"))
        self.reading.set()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


class _DelayedStore(InMemoryInvocationStore):
    def __init__(self, terminal_status: InvocationStatus) -> None:
        super().__init__()
        self.terminal_status = terminal_status
        self.terminalizing = asyncio.Event()
        self.release = asyncio.Event()
        self.terminal_saves = 0

    async def save(self, invocation: Invocation) -> Invocation:
        if invocation.status is self.terminal_status:
            self.terminal_saves += 1
            self.terminalizing.set()
            await self.release.wait()
        return await super().save(invocation)


class _DeniedQuota:
    async def reserve(self, invocation: Invocation, binding: Binding) -> None:
        raise PermissionError("quota denied")

    async def observe(self, invocation: Invocation) -> None:
        pass


class _DelayedAdmissionStore(InMemoryInvocationStore):
    def __init__(self) -> None:
        super().__init__()
        self.admitted = asyncio.Event()
        self.release = asyncio.Event()

    async def claim(self, invocation: Invocation) -> Invocation:
        admitted = await super().claim(invocation)
        self.admitted.set()
        await self.release.wait()
        return admitted


@pytest.mark.parametrize("cancel_again", [False, True])
async def test_cancellation_during_quota_failure_preserves_failed_recording(
    cancel_again: bool,
) -> None:
    store = _DelayedStore(InvocationStatus.FAILED)
    effects, egress, arguments = _fixture(store, quota=_DeniedQuota())

    def unexpected(_: httpx.Request) -> httpx.Response:
        pytest.fail("quota denied request dispatched")

    with override_transport(httpx.MockTransport(unexpected)):
        consumer = asyncio.create_task(anext(egress.stream(**arguments)))
        await asyncio.wait_for(store.terminalizing.wait(), 1)
        consumer.cancel()
        await asyncio.sleep(0)
        if cancel_again:
            consumer.cancel()
            await asyncio.sleep(0)
        store.release.set()
        with pytest.raises(asyncio.CancelledError):
            await consumer
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.FAILED
    assert row.dispatch_active is False
    assert store.terminal_saves == 1
    assert effects.usage_log.events_for("model") == ()


@pytest.mark.parametrize("cancel_again", [False, True])
async def test_cancellation_during_admission_refuses_dispatch_after_admission(
    cancel_again: bool,
) -> None:
    store = _DelayedAdmissionStore()
    effects, egress, arguments = _fixture(store)

    def unexpected(_: httpx.Request) -> httpx.Response:
        pytest.fail("cancelled admission dispatched")

    with override_transport(httpx.MockTransport(unexpected)):
        consumer = asyncio.create_task(anext(egress.stream(**arguments)))
        await asyncio.wait_for(store.admitted.wait(), 1)
        consumer.cancel()
        await asyncio.sleep(0)
        if cancel_again:
            consumer.cancel()
            await asyncio.sleep(0)
        store.release.set()
        with pytest.raises(asyncio.CancelledError):
            await consumer
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.FAILED
    assert row.dispatch_active is False
    assert effects.usage_log.events_for("model") == ()


@pytest.mark.parametrize("cancel_again", [False, True])
async def test_consumer_cancellation_waits_for_canonical_unknown(cancel_again: bool) -> None:
    store = _DelayedStore(InvocationStatus.UNKNOWN)
    effects, egress, arguments = _fixture(store)
    source = _BlockedBytes()
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))):
        stream = egress.stream(**arguments)
        await anext(stream)
        await source.reading.wait()
        consumer = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        consumer.cancel()
        try:
            await asyncio.wait_for(store.terminalizing.wait(), 1)
            assert source.closed
            assert not consumer.done()
            if cancel_again:
                consumer.cancel()
                await asyncio.sleep(0)
                assert not consumer.done(), "cancellation must still await canonical recording"
        finally:
            store.release.set()
            with pytest.raises(asyncio.CancelledError):
                await consumer
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.UNKNOWN
    assert row.dispatch_active is False
    assert effects.usage_log.events_for("model") == ()
    assert store.terminal_saves == 1


@pytest.mark.parametrize("cancel_close", [False, True])
async def test_close_after_provider_completion_finishes_recording(cancel_close: bool) -> None:
    store = _DelayedStore(InvocationStatus.COMPLETED)
    effects, egress, arguments = _fixture(store)
    source = _Bytes([_frame(_chunk("done", finish="stop")), b"data: [DONE]\n\n"])
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))):
        stream = egress.stream(**arguments)
        await anext(stream)
        await asyncio.wait_for(store.terminalizing.wait(), 1)
        closer = asyncio.create_task(stream.aclose())
        try:
            await asyncio.sleep(0)
            assert source.closed
            assert not closer.done()
            if cancel_close:
                closer.cancel()
                await asyncio.sleep(0)
                assert not closer.done(), (
                    "known completion must finish recording before close exits"
                )
        finally:
            store.release.set()
            if cancel_close:
                with pytest.raises(asyncio.CancelledError):
                    await closer
            else:
                await closer
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.COMPLETED
    assert row.dispatch_active is False
    assert source.close_count == store.terminal_saves == 1
    assert row.usage is None
    events = effects.usage_log.events_for("model")
    assert len(events) == 1
    assert events[0].usage_reported is False


@pytest.mark.parametrize("cancel_close", [False, True])
@pytest.mark.parametrize("failure", [httpx.ReadError("interrupted"), b"data: invalid\n\n", b""])
async def test_close_after_provider_failure_preserves_unknown_recording(
    cancel_close: bool,
    failure: bytes | Exception,
) -> None:
    store = _DelayedStore(InvocationStatus.UNKNOWN)
    effects, egress, arguments = _fixture(store)
    source = _Bytes([_frame(_chunk("partial")), failure])
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))):
        stream = egress.stream(**arguments)
        await anext(stream)
        await asyncio.wait_for(store.terminalizing.wait(), 1)
        assert source.closed
        closer = asyncio.create_task(stream.aclose())
        await asyncio.sleep(0)
        if cancel_close:
            closer.cancel()
            await asyncio.sleep(0)
            closer.cancel()
            await asyncio.sleep(0)
        store.release.set()
        if cancel_close:
            with pytest.raises(asyncio.CancelledError):
                await closer
        else:
            await closer
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.UNKNOWN
    assert row.dispatch_active is False
    assert effects.usage_log.events_for("model") == ()
    assert source.close_count == store.terminal_saves == 1


async def test_cancellation_after_connect_failure_preserves_proven_failed_recording() -> None:
    store = _DelayedStore(InvocationStatus.FAILED)
    effects, egress, arguments = _fixture(store)

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    with override_transport(httpx.MockTransport(fail)):
        stream = egress.stream(**arguments)
        consumer = asyncio.create_task(anext(stream))
        await asyncio.wait_for(store.terminalizing.wait(), 1)
        consumer.cancel()
        await asyncio.sleep(0)
        consumer.cancel()
        await asyncio.sleep(0)
        store.release.set()
        with pytest.raises(asyncio.CancelledError):
            await consumer
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.FAILED
    assert row.dispatch_active is False
    assert store.terminal_saves == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_errors_close_without_reading_or_recording_usage(status: int) -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes([b"gateway failure containing scoped-secret"])
    error = LlmAuthError if status == 401 else LlmHttpError
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(status, stream=source))),
        pytest.raises(error) as raised,
    ):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    assert isinstance(raised.value, LlmAuthError | LlmHttpError)
    assert raised.value.status_code == status
    assert source.closed and source.read == 0
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.UNKNOWN
    assert "scoped-secret" not in (row.error or "")
    assert effects.usage_log.events_for("model") == ()


@pytest.mark.parametrize("failure", [httpx.ReadError, httpx.ConnectError, httpx.ReadTimeout])
async def test_transport_failure_after_response_is_unknown(failure: type[httpx.HTTPError]) -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes([_frame(_chunk("partial")), failure("interrupted")])
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))),
        pytest.raises(failure),
    ):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    assert source.closed
    assert (await _rows(effects))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "completion_tokens": 3}])
async def test_missing_or_invalid_usage_remains_unreported(usage: dict[str, Any] | None) -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes(
        [
            _frame(_chunk("done", finish="stop")),
            _frame({"choices": [], "usage": usage}),
            b"data: [DONE]\n\n",
        ]
    )
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.COMPLETED
    assert isinstance(row.result, dict)
    assert row.usage is None and "usage" not in row.result
    assert effects.usage_log.events_for("model")[0].usage_reported is False


async def test_sqlite_replay_after_reopening_dispatches_only_once(tmp_path: Path) -> None:
    database = tmp_path / "invocations.sqlite"
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            stream=_Bytes(
                [
                    _frame(_chunk("durable", finish="stop")),
                    b"data: [DONE]\n\n",
                ]
            ),
        )

    with override_transport(httpx.MockTransport(handle)):
        async with aiosqlite.connect(database) as connection:
            store = SqliteInvocationStore(connection)
            await store.ensure_schema()
            effects, egress, arguments = _fixture(store)
            _ = [chunk async for chunk in egress.stream(**arguments)]
            original = (await _rows(effects))[0]
        async with aiosqlite.connect(database) as connection:
            reopened = SqliteInvocationStore(connection)
            effects, egress, arguments = _fixture(reopened)
            replay = [chunk async for chunk in egress.stream(**arguments)]
            stored = (await _rows(effects))[0]
    assert len(requests) == 1
    assert stored.invocation_id == original.invocation_id
    assert stored.result == original.result
    assert replay[0]["_maistro_replayed"] is True
    assert replay[0]["choices"][0]["delta"]["content"] == "durable"


@pytest.mark.parametrize("ending", [b"", b"data: [DONE]\n", b"data: [DONE]"])
async def test_finished_choices_do_not_make_truncated_eof_successful(ending: bytes) -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes([_frame(_chunk("finished", finish="stop")), ending])
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))),
        pytest.raises(ModelStreamProtocolError),
    ):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    assert (await _rows(effects))[0].status is InvocationStatus.UNKNOWN


async def test_split_sse_frames_and_multiline_events_preserve_raw_chunks() -> None:
    effects, egress, arguments = _fixture()
    chunk = _chunk("snowman: ☃", finish="stop")
    encoded = json.dumps(chunk, ensure_ascii=False).replace(', "model"', ',\ndata: "model"')
    wire = f": keepalive\r\nevent: message\r\ndata: {encoded}\r\n\r\ndata: [DONE]\r\n\r\n".encode()
    source = _Bytes([wire[i : i + 1] for i in range(len(wire))])
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))):
        actual = [chunk async for chunk in egress.stream(**arguments)]
    assert actual == [chunk]
    assert (await _rows(effects))[0].status is InvocationStatus.COMPLETED


async def test_interleaved_choices_assemble_tool_fragments_by_both_indices() -> None:
    effects, egress, arguments = _fixture()
    chunks = [
        {
            "choices": [
                {
                    "index": 1,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "call-second",
                                "type": "function",
                                "function": {"name": "second", "arguments": "{"},
                            },
                            {
                                "index": 0,
                                "id": "call-first",
                                "type": "function",
                                "function": {"name": "get_", "arguments": '{"city":'},
                            },
                        ]
                    },
                },
                {"index": 0, "delta": {"role": "assistant", "content": "answer"}},
            ]
        },
        {
            "choices": [
                {"index": 0, "delta": {"content": "!"}, "finish_reason": "stop"},
                {
                    "index": 1,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-first",
                                "type": "function",
                                "function": {"name": "weather", "arguments": '"Paris"}'},
                            },
                            {"index": 1, "function": {"arguments": "}"}},
                        ]
                    },
                },
            ]
        },
        {"choices": [{"index": 1, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    source = _Bytes([*map(_frame, chunks), b"data: [DONE]\n\n"])
    with override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))):
        actual = [chunk async for chunk in egress.stream(**arguments)]
    assert actual == chunks
    result = (await _rows(effects))[0].result
    assert isinstance(result, dict)
    choices = result["choices"]
    assert [choice["index"] for choice in choices] == [0, 1]
    assert choices[0]["message"]["content"] == "answer!"
    assert choices[1]["message"]["tool_calls"] == [
        {
            "id": "call-first",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
        },
        {
            "id": "call-second",
            "type": "function",
            "function": {"name": "second", "arguments": "{}"},
        },
    ]


async def test_one_finished_choice_does_not_hide_an_unfinished_choice() -> None:
    effects, egress, arguments = _fixture()
    chunk = {
        "choices": [
            {"index": 0, "delta": {"content": "first"}, "finish_reason": "stop"},
            {"index": 1, "delta": {"content": "unfinished"}},
        ]
    }
    source = _Bytes([_frame(chunk), b"data: [DONE]\n\n"])
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))),
        pytest.raises(ModelStreamProtocolError),
    ):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    assert (await _rows(effects))[0].status is InvocationStatus.UNKNOWN


async def test_content_after_a_choice_finished_is_not_a_completed_result() -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes(
        [
            _frame(_chunk("first", finish="stop")),
            _frame(_chunk("contradiction")),
            b"data: [DONE]\n\n",
        ]
    )
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))),
        pytest.raises(ModelStreamProtocolError),
    ):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    assert (await _rows(effects))[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize(
    "data",
    [
        "[]",
        "null",
        "{}",
        '{"choices":{}}',
        '{"choices":[{"index":false,"delta":{}}]}',
        '{"choices":[{"index":-1,"delta":{}}]}',
        '{"choices":[{"index":0,"delta":[],"finish_reason":"stop"}]}',
        '{"choices":[{"index":0,"delta":{},"finish_reason":true}]}',
        '{"choices":[{"index":0,"delta":{"tool_calls":[{"index":-1}]}}]}',
    ],
)
async def test_malformed_chunk_is_unknown(data: str) -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes([f"data: {data}\n\n".encode(), b"data: [DONE]\n\n"])
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))),
        pytest.raises(ModelStreamProtocolError),
    ):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    assert (await _rows(effects))[0].status is InvocationStatus.UNKNOWN


_INVALID_DELTAS: list[tuple[dict[str, Any], dict[str, Any]]] = [
    ({"content": "kept"}, {"content": 123}),
    ({"content": "kept"}, {"content": {}}),
    ({"reasoning_content": "thinking"}, {"reasoning_content": []}),
    ({"function_call": {"arguments": "{"}}, {"function_call": {"arguments": 123}}),
    ({}, {"function_call": {"arguments": {}}}),
    (
        {"tool_calls": [{"index": 0, "id": "original"}]},
        {"tool_calls": [{"index": 0, "id": "different"}]},
    ),
    ({"role": "assistant"}, {"role": "user"}),
    (
        {"tool_calls": [{"index": 0, "type": "function"}]},
        {"tool_calls": [{"index": 0, "type": "different"}]},
    ),
    ({}, {"tool_calls": [{"index": 0, "id": 123}]}),
    ({}, {"tool_calls": [{"index": 0, "function": {"name": 123}}]}),
]


@pytest.mark.parametrize("initial,invalid", _INVALID_DELTAS)
def test_accumulator_rejects_invalid_text_and_conflicting_metadata(
    initial: dict[str, Any],
    invalid: dict[str, Any],
) -> None:
    accumulator = ChatStreamAccumulator()
    accumulator.add(_chunk(**initial))
    with pytest.raises(ModelStreamProtocolError):
        accumulator.add(_chunk(**invalid, finish="stop"))


@pytest.mark.parametrize("initial,invalid", _INVALID_DELTAS)
async def test_invalid_text_and_conflicting_metadata_are_unknown(
    initial: dict[str, Any],
    invalid: dict[str, Any],
) -> None:
    effects, egress, arguments = _fixture()
    source = _Bytes(
        [
            _frame(_chunk(**initial)),
            _frame(_chunk(**invalid, finish="stop")),
            b"data: [DONE]\n\n",
        ]
    )
    with (
        override_transport(httpx.MockTransport(lambda _: httpx.Response(200, stream=source))),
        pytest.raises(ModelStreamProtocolError),
    ):
        _ = [chunk async for chunk in egress.stream(**arguments)]
    row = (await _rows(effects))[0]
    assert row.status is InvocationStatus.UNKNOWN
    assert row.result is None
    assert effects.usage_log.events_for("model") == ()
