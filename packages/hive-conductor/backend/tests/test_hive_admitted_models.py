"""Shipped Hive model callers on SQLite; every HTTP request uses MockTransport."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from adapters.llm_governed import GovernedModelFailure, model_effect
from config import get_settings
from fastapi import Request
from models.schemas import ChatCompletionRequest
from models.workspace import WorkspacePresentation
from routes import chat as chat_routes
from routes import voice as voice_routes
from services import chat_completion as chat
from services import chat_runs, default_workspace, workspace_authority
from services.engine import get_engine

from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.invocation import InvocationStatus, ReconciliationDisposition
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.container import Container, create_container
from maistro.graph.definitions import Graph, Node
from maistro.http import get_shared_client, set_test_transport
from maistro.identity import Principal
from maistro.observability.correlation import bind_execution_context
from maistro.policy.types import Decision, PolicyVerdict
from maistro.quota.invocation_quota import QuotaBudget
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.types.config import AgentConfig

_WORKSPACE = "hive-model-workspace"
_ACTOR = "hive-model-actor"
_BINDING = "hive-model-binding"
_MODEL = "configured-model"
_MESSAGES = [{"role": "user", "content": "hello"}]


def _body(content: str = "answer", tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "model": _MODEL,
        "choices": [{"message": {"role": "assistant", "content": content, "tool_calls": tools}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
    }


def _sse(content: str = "answer", *, finished: bool = True) -> str:
    chunks = [{"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]}]
    if finished:
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + (
        "data: [DONE]\n\n" if finished else ""
    )


@dataclass
class Setup:
    container: Container
    path: Path
    project_id: str
    calls: AdmittedModelCalls
    requests: list[httpx.Request] = field(default_factory=list)
    responses: list[Any] = field(default_factory=list)

    def grants(self) -> list[tuple[Any, ...]]:
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT binding_id, payload_json FROM capability_bindings ORDER BY binding_id"
            ).fetchall()


@pytest.fixture
async def setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[Setup]:
    options = getattr(request, "param", {})
    providers = tmp_path / "providers.yaml"
    providers.write_text(
        f"models:\n  - name: {_MODEL}\n    provider: openai\n"
        "    cost_input: 1.0\n    cost_output: 2.0\n    latency_p50_ms: 1\n"
    )
    path = tmp_path / "runtime.sqlite3"
    database_url = f"sqlite:///{path}"
    initial = await create_container(AgentConfig(database_url=database_url, router_api_key="test"))
    await initial.workspace_store.create(
        name="Hive models", creator_user_id=_ACTOR, workspace_id=_WORKSPACE
    )
    project = await initial.project_scope_store.root_for_workspace(_WORKSPACE)
    await initial.aclose()
    bindings = [
        {
            "binding_id": _BINDING,
            "project_id": project.project_id,
            "provider_name": options.get("pin", _MODEL),
            "disabled": options.get("disabled", False),
        }
    ]
    if options.get("foreign_project"):
        bindings[0]["project_id"] = "foreign"
    if options.get("foreign_node"):
        bindings[0]["node_id"] = "foreign"
    if options.get("ambiguous"):
        bindings.append({"binding_id": "second", "project_id": project.project_id})
    if options.get("unconfigured"):
        bindings = []
    owner = await create_container(
        AgentConfig(
            router_api_key="test",
            database_url=database_url,
            workspace_id=_WORKSPACE,
            provider_config_path=str(providers),
            litellm_url="https://configured.gateway.test",
            litellm_key="" if options.get("missing_key") else "scoped-test-key",
            model_bindings=bindings,
        )
    )
    calls = AdmittedModelCalls(
        owner.capability_effects,
        registry=owner.provider_registry,
        router=owner.llm_router,
        endpoint=GatewayEndpoint(base_url=owner.config.litellm_url),
        run_store=owner.run_store,
        binding_ids=tuple(binding.binding_id for binding in owner.config.model_bindings),
    )
    monkeypatch.setattr(
        get_engine(), "_agent_port", SimpleNamespace(container=owner, admitted_calls=calls)
    )
    workspace_authority.presentation_store()[_WORKSPACE] = WorkspacePresentation(
        workspace_id=_WORKSPACE, persona_template_id="personal", updated_at=datetime.now(UTC)
    )
    monkeypatch.setattr(get_settings(), "llm_http_variant", "chat_completions")
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://ambient.must-not-win.test")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "ambient-key-must-not-be-borrowed")
    monkeypatch.setenv("LITELLM_API_BASE", "https://raw.must-not-run.test")
    monkeypatch.setenv("LITELLM_API_KEY", "raw-key-must-not-be-borrowed")
    monkeypatch.setattr(chat, "_build_system_prompt", lambda _: "system")
    state = Setup(owner, path, project.project_id, calls)

    def transport(sent: httpx.Request) -> httpx.Response:
        if sent.url.host == "127.0.0.1":
            assert sent.url.path == "/v1/widgets/screenshot"
            return httpx.Response(200, json={"screenshot": "fixture-image"})
        state.requests.append(sent)
        assert sent.url.host == "configured.gateway.test"
        response = state.responses.pop(0) if state.responses else _body()
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        if isinstance(response, str):
            return httpx.Response(200, text=response, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=response)

    set_test_transport(httpx.MockTransport(transport))
    chat_runs.reset_for_tests()
    default_workspace.reset_for_tests()
    try:
        yield state
    finally:
        set_test_transport(None)
        chat_runs.reset_for_tests()
        default_workspace.reset_for_tests()
        await owner.aclose()


async def _running(s: Setup) -> tuple[str, str, str]:
    graph = Graph(
        name="Hive chat",
        workspace_id=_WORKSPACE,
        project_id=s.project_id,
        nodes=[Node(node_id="chat", node_type="chat", name="chat")],
    )
    runs = s.container.run_store
    run = await runs.create_run(graph, initial_status=RunStatus.QUEUED, actor_principal_id=_ACTOR)
    await runs.transition_run(run.run_id, RunStatus.RUNNING)
    node = await runs.create_node_run(run.run_id, node_id="chat")
    for step in transition_path(node.status, RunStatus.RUNNING):
        node = await runs.transition_node_run(node.node_run_id, step)
    attempt = await runs.create_attempt(node.node_run_id, lease_holder="test-worker")
    await runs.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    return run.run_id, node.node_run_id, attempt.attempt_id


def _context(identity: tuple[str, str, str], **extra: str):
    return bind_execution_context(
        run_id=identity[0], node_run_id=identity[1], attempt_id=identity[2], **extra
    )


async def _later(s: Setup, identity: tuple[str, str, str]) -> tuple[str, str, str]:
    runs = s.container.run_store
    old = await runs.get_attempt(identity[2])
    await runs.transition_attempt(
        old.attempt_id, AttemptStatus.FAILED, fencing_token=old.execution_lease.fencing_token
    )
    later = await runs.create_attempt(identity[1], lease_holder="later-worker")
    await runs.transition_attempt(
        later.attempt_id, AttemptStatus.RUNNING, fencing_token=later.execution_lease.fencing_token
    )
    return identity[0], identity[1], later.attempt_id


async def _history(s: Setup, identity: tuple[str, str, str], key: str = "hive-chat:turn:0"):
    return await s.container.invocation_store.list_effect(
        run_id=identity[0], node_run_id=identity[1], binding_id=_BINDING, effect_key=key
    )


def _request(**extra: Any) -> ChatCompletionRequest:
    return ChatCompletionRequest(messages=_MESSAGES, model="request-alias", **extra)


async def test_shipped_port_uses_persisted_authority_options_and_scoped_credentials(setup: Setup):
    identity = await _running(setup)
    before = setup.grants()
    with _context(identity):
        result = await chat.build_llm_port().complete(
            _request(
                temperature=0.2,
                max_tokens=23,
                response_format={"type": "json_object"},
                tool_choice="none",
                effect_key="untrusted",
                workspace_id="foreign",
            )
        )
    assert result["choices"][0]["message"]["content"] == "answer"
    (invocation,) = await _history(setup, identity)
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.actor_id == _ACTOR
    assert invocation.binding.workspace_id == _WORKSPACE
    assert invocation.binding.project_id == setup.project_id
    assert invocation.attempt_id == identity[2]
    assert invocation.usage.model == _MODEL
    assert invocation.usage.cost_cents == 2
    assert len(setup.requests) == 1
    sent = setup.requests[0]
    assert sent.headers["Authorization"] == "Bearer scoped-test-key"
    assert sent.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 120.0)
    payload = json.loads(sent.content)
    assert payload["model"] == _MODEL
    assert payload["messages"] == _MESSAGES
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 23
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["tool_choice"] == "none"
    assert "effect_key" not in payload and "workspace_id" not in payload
    assert setup.grants() == before
    assert len(setup.container.usage_log.events_for(_MODEL)) == 1


@pytest.mark.parametrize(
    "setup",
    [
        {"unconfigured": True},
        {"missing_key": True},
        {"ambiguous": True},
        {"disabled": True},
        {"foreign_project": True},
        {"foreign_node": True},
    ],
    indirect=True,
)
async def test_configuration_refusal_cannot_borrow_ambient_grants(setup: Setup):
    identity = await _running(setup)
    before = setup.grants()
    with _context(identity), pytest.raises(GovernedModelFailure):
        await chat.build_llm_port().complete(_request())
    assert setup.requests == []
    assert setup.grants() == before


@pytest.mark.parametrize(
    "condition", ["missing-context", "forged", "foreign-context", "revoked", "terminal"]
)
async def test_invalid_admission_has_no_http(setup: Setup, condition: str):
    identity = await _running(setup)
    before = setup.grants()
    if condition == "revoked":
        await setup.container.capability_effects.bindings.revoke(_BINDING)
        before = setup.grants()
    if condition == "terminal":
        await setup.container.run_store.transition_run(identity[0], RunStatus.CANCELLED)
    if condition == "missing-context":
        identity = ("", "", "")
    elif condition == "forged":
        identity = ("invented", "invented", "invented")
    extra = {"workspace_id": "foreign"} if condition == "foreign-context" else {}
    with _context(identity, **extra), pytest.raises(GovernedModelFailure):
        await chat.build_llm_port().complete(_request())
    assert setup.requests == []
    assert setup.grants() == before


@pytest.mark.parametrize("condition", ["policy", "quota"])
async def test_policy_and_actor_quota_refuse_before_http(setup: Setup, condition: str):
    identity = await _running(setup)
    if condition == "policy":

        async def deny(*args: Any) -> PolicyVerdict:
            return PolicyVerdict(Decision.DENY, reason="fixture refusal", rule="fixture")

        setup.calls._effects = setup.container.capability_effects.with_policy_evaluator(deny)
    else:
        await setup.container.capability_effects.quota.register_budget(
            QuotaBudget(
                budget_id="zero",
                unit="requests",
                limit=0,
                period_start=0,
                period_end=2**62,
                coverage_ref="fixture",
                opening_spend=0,
                workspace_id=_WORKSPACE,
                principal_id=_ACTOR,
                capability="model.chat",
            )
        )
    before = setup.grants()
    with _context(identity), pytest.raises(GovernedModelFailure):
        await chat.build_llm_port().complete(_request())
    assert setup.requests == []
    assert setup.grants() == before


@pytest.mark.parametrize("unknown", [False, True])
async def test_rebuilt_port_later_attempt_replays_or_refuses_unknown(setup: Setup, unknown: bool):
    identity = await _running(setup)
    if unknown:
        setup.responses = [httpx.ReadTimeout("provider outcome unknown")]
    with _context(identity):
        if unknown:
            with pytest.raises(GovernedModelFailure):
                await chat.build_llm_port().complete(_request())
        else:
            await chat.build_llm_port().complete(_request())
    later = await _later(setup, identity)
    with _context(later):
        if unknown:
            with pytest.raises(GovernedModelFailure):
                await chat.build_llm_port().complete(_request())
        else:
            result = await chat.build_llm_port().complete(_request())
            assert result["choices"][0]["message"]["content"] == "answer"
    (invocation,) = await _history(setup, identity)
    assert invocation.status is (
        InvocationStatus.UNKNOWN if unknown else InvocationStatus.COMPLETED
    )
    assert invocation.attempt_id == identity[2]
    assert len(setup.requests) == 1
    assert len(setup.container.usage_log.events_for(_MODEL)) == (0 if unknown else 1)


async def test_not_applied_reconciliation_allows_normal_later_attempt(setup: Setup):
    identity = await _running(setup)
    setup.responses = [httpx.ReadTimeout("unknown")]
    with _context(identity), pytest.raises(GovernedModelFailure):
        await chat.build_llm_port().complete(_request())
    (original,) = await _history(setup, identity)
    await setup.container.capability_effects.invocations.reconcile(
        original.invocation_id,
        disposition=ReconciliationDisposition.NOT_APPLIED,
        source="operator",
        actor="fixture-operator",
        reason="fixture provider proved no application",
        evidence={"receipt": "fixture"},
        workspace_id=_WORKSPACE,
        project_id=setup.project_id,
    )
    later = await _later(setup, identity)
    with _context(later):
        result = await chat.build_llm_port().complete(_request())
    assert result["choices"][0]["message"]["content"] == "answer"
    history = await _history(setup, identity)
    assert len(history) == len(setup.requests) == 2
    assert history[-1].attempt_id == later[2]
    assert history[-1].status is InvocationStatus.COMPLETED


async def test_dashboard_positions_are_distinct_and_replay_across_attempts(
    setup: Setup, monkeypatch
):
    identity = await _running(setup)
    tool_calls = [
        {
            "id": f"call-{index}",
            "type": "function",
            "function": {"name": "analyze_dashboard", "arguments": "{}"},
        }
        for index in range(2)
    ]
    setup.responses = [
        _body("", tool_calls),
        _body("vision one"),
        _body("vision two"),
        _body("summary"),
    ]

    async def tool(name, args, user_id, gate_id, **kwargs):
        result = await chat._tool_analyze_dashboard(args, user_id, None)
        return result, "analyzed"

    monkeypatch.setattr(chat, "_gated_execute_tool", tool)
    before = setup.grants()
    with _context(identity):
        first = await chat.run_chat_completion(_request(), user_id=_ACTOR)
    later = await _later(setup, identity)
    with _context(later):
        second = await chat.run_chat_completion(_request(), user_id=_ACTOR)
    assert first == second
    assert first["choices"][0]["message"]["content"] == "summary"
    assert len(setup.requests) == 4
    for index in range(2):
        (invocation,) = await _history(
            setup, identity, f"hive-chat:turn:0:tool:{index}:dashboard-analysis"
        )
        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.actor_id == _ACTOR and invocation.attempt_id == identity[2]
        sent = setup.requests[index + 1]
        payload = json.loads(sent.content)
        assert sent.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 60.0
        )
        assert payload["max_tokens"] == 2000
        assert "temperature" not in payload
        assert payload["messages"][0]["content"][1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,fixture-image"},
        }
    assert len(await _history(setup, identity, "hive-chat:turn:1")) == 1
    assert setup.grants() == before


@pytest.mark.parametrize("response", ["transport", "partial", "empty"])
async def test_internal_stream_never_redispatches_ambiguous_or_empty_output(
    setup: Setup, response: str
):
    identity = await _running(setup)
    setup.responses = [
        {
            "transport": httpx.ReadTimeout("unknown"),
            "partial": _sse("partial", finished=False),
            "empty": _sse(""),
        }[response]
    ]
    with _context(identity), pytest.raises(GovernedModelFailure):
        _ = [
            event async for event in chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        ]
    assert len(setup.requests) == 1
    history = await _history(setup, identity)
    assert len(history) == 1
    assert history[0].status is (
        InvocationStatus.COMPLETED if response == "empty" else InvocationStatus.UNKNOWN
    )


async def test_internal_complete_does_not_convert_model_failure_to_content(setup: Setup):
    identity = await _running(setup)
    setup.responses = [httpx.ReadTimeout("unknown")]
    with _context(identity), pytest.raises(GovernedModelFailure):
        await chat.run_chat_completion(_request(), user_id=_ACTOR)
    assert len(setup.requests) == 1


async def test_model_tool_failure_escapes_tool_result_wrapper(setup: Setup, monkeypatch):
    async def failed(*args, **kwargs):
        raise GovernedModelFailure()

    monkeypatch.setattr(chat, "_execute_tool", failed)
    with pytest.raises(GovernedModelFailure):
        await chat._gated_execute_tool("analyze_dashboard", {}, _ACTOR, "gate")


def _principal() -> Request:
    return Request({"type": "http", "state": {"principal": Principal(user_id=_ACTOR)}})


@pytest.mark.parametrize("stream", [False, True])
async def test_public_route_keeps_conversation_containment_and_persisted_scope(
    setup: Setup, stream: bool
):
    request = _request(
        workspace_id=_WORKSPACE,
        tools=[{"type": "function", "function": {"name": "shell"}}],
        tools_scope="chat",
        effect_key="forged",
        temperature=0.4,
        max_tokens=17,
    )
    before = setup.grants()
    if stream:
        response = await chat_routes.stream_complete(request, _principal())
        frames = [
            json.loads(frame.removeprefix("data: ").strip())
            async for frame in response.body_iterator
        ]
        assert len(frames) == 1 and frames[0]["type"] == "done"
        assert frames[0]["content"] == "answer"
        run_id = frames[0]["run_id"]
    else:
        result = await chat_routes.complete(request, _principal())
        assert result["choices"][0]["message"]["content"] == "answer"
        run_id = result["run_id"]
    run = await setup.container.run_store.get_run(run_id)
    assert run.status is RunStatus.COMPLETED
    assert run.actor_principal_id == _ACTOR
    assert run.workspace_id == _WORKSPACE and run.project_id == setup.project_id
    payload = json.loads(setup.requests[0].content)
    assert payload["stream"] is False
    assert "tools" not in payload
    assert payload["temperature"] == 0.4 and payload["max_tokens"] == 17
    assert len(setup.requests) == 1
    assert setup.grants() == before


async def test_public_stream_reports_bounded_failure_and_failed_canonical_execution(setup: Setup):
    setup.responses = [httpx.ReadTimeout("secret detail must not escape")]
    response = await chat_routes.stream_complete(_request(workspace_id=_WORKSPACE), _principal())
    frames = [
        json.loads(frame.removeprefix("data: ").strip()) async for frame in response.body_iterator
    ]
    (failure,) = frames
    assert failure["type"] == "done" and failure["status"] == "failed"
    assert failure["error"]["code"] == "chat_execution_failed"
    assert failure["content"].startswith("Error:")
    assert "secret detail" not in json.dumps(failure)
    run = await setup.container.run_store.get_run(failure["run_id"])
    assert run.status is RunStatus.FAILED and run.result is None
    (node,) = await setup.container.run_store.list_node_runs(run.run_id)
    (attempt,) = await setup.container.run_store.list_attempts(node.node_run_id)
    assert attempt.status is AttemptStatus.FAILED
    (invocation,) = await _history(setup, (run.run_id, node.node_run_id, attempt.attempt_id))
    assert invocation.status is InvocationStatus.UNKNOWN
    assert len(setup.requests) == 1


def _responses_body() -> dict[str, Any]:
    return {
        "id": "responses-id",
        "model": _MODEL,
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "think"}]},
            {"type": "message", "content": [{"type": "output_text", "text": "answer"}]},
        ],
        "usage": {"input_tokens": 1000, "output_tokens": 500},
    }


def _responses_sse() -> str:
    events = [
        {"type": "response.output_item.added", "item": {"type": "message", "id": "item"}},
        {"type": "response.output_text.delta", "delta": ""},
        {"type": "response.output_text.delta", "delta": "answer"},
        {"type": "response.reasoning_summary_text.delta", "delta": "think"},
        {"type": "response.output_text.done", "text": "answer"},
        {"type": "response.completed", "response": _responses_body()},
    ]
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


@pytest.mark.parametrize("variant", ["auto", "responses"])
@pytest.mark.parametrize("stream", [False, True])
async def test_responses_setting_preserves_ingress_options_normalization_and_usage(
    setup: Setup, monkeypatch, variant: str, stream: bool
):
    monkeypatch.setattr(get_settings(), "llm_http_variant", variant)
    identity = await _running(setup)
    setup.responses = [_responses_sse() if stream else _responses_body()]
    with _context(identity):
        port = chat.build_llm_port()
        request = _request(temperature=0.15, max_tokens=21, response_format={"type": "json_object"})
        if stream:
            chunks = [chunk async for chunk in port.stream(request)]
            deltas = [
                choice.get("delta", {}) for chunk in chunks for choice in chunk.get("choices", [])
            ]
            assert "".join(delta.get("content", "") for delta in deltas) == "answer"
            assert "".join(delta.get("reasoning_content", "") for delta in deltas) == "think"
            assert any(
                choice.get("finish_reason") == "stop"
                for chunk in chunks
                for choice in chunk.get("choices", [])
            )
        else:
            result = await port.complete(request)
            assert result["choices"][0]["message"]["content"] == "answer"
            assert result["choices"][0]["message"]["reasoning_content"] == "think"
    assert len(setup.requests) == 1
    sent = setup.requests[0]
    assert sent.url.path == "/v1/responses"
    payload = json.loads(sent.content)
    assert payload["input"] == _MESSAGES
    assert payload["temperature"] == 0.15 and payload["max_output_tokens"] == 21
    assert payload["text"] == {"format": {"type": "json_object"}}
    assert payload["stream"] is stream
    (invocation,) = await _history(setup, identity)
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.usage.input_units == 1000 and invocation.usage.output_units == 500
    assert len(setup.container.usage_log.events_for(_MODEL)) == 1


@pytest.mark.parametrize("trusted", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_auto_fallback_requires_exact_nonapplication_proof(
    setup: Setup, monkeypatch, trusted: bool, stream: bool
):
    monkeypatch.setattr(get_settings(), "llm_http_variant", "auto")
    identity = await _running(setup)
    rejection = {
        "error": {
            "type": "maistro.unsupported_ingress.v1",
            "ingress": "responses",
            "model": _MODEL,
            "dispatch": "not_started",
            "effect": "not_applied",
        }
    }
    setup.responses = [
        httpx.Response(
            501 if trusted else 404, json=rejection if trusted else {"error": "unsupported"}
        )
    ]
    if trusted:
        setup.responses.append(_sse() if stream else _body())
    with _context(identity):

        async def call():
            port = chat.build_llm_port()
            return (
                [chunk async for chunk in port.stream(_request())]
                if stream
                else await port.complete(_request())
            )

        if trusted:
            await call()
        else:
            with pytest.raises(GovernedModelFailure):
                await call()
    assert [sent.url.path for sent in setup.requests] == (
        ["/v1/responses", "/v1/chat/completions"] if trusted else ["/v1/responses"]
    )
    history = await _history(setup, identity)
    assert len(history) == (2 if trusted else 1)
    assert history[-1].status is (
        InvocationStatus.COMPLETED if trusted else InvocationStatus.UNKNOWN
    )


async def test_governed_complete_and_stream_reuse_the_open_pooled_client(setup: Setup):
    identity = await _running(setup)
    setup.responses = [_body(), _sse()]
    with _context(identity):
        port = chat.build_llm_port()
        before = get_shared_client(timeout=120.0)
        await port.complete(_request())
        with model_effect("hive-chat:continuation"):
            chunks = [chunk async for chunk in port.stream(_request())]
        after = get_shared_client(timeout=120.0)
    assert before is after and not after.is_closed
    assert chunks[0]["choices"][0]["delta"]["content"] == "answer"
    assert len(setup.requests) == 2
    assert all(sent.url.path == "/v1/chat/completions" for sent in setup.requests)
    assert all(sent.headers["Authorization"] == "Bearer scoped-test-key" for sent in setup.requests)


async def test_voice_intent_uses_the_same_admitted_port_and_default_workspace(setup: Setup):
    default_workspace._claims_store().put_if_absent(
        default_workspace.claim_key(_ACTOR, 1),
        {"user_id": _ACTOR, "workspace_id": _WORKSPACE, "generation": 1},
    )
    result = await voice_routes.voice_intent(
        voice_routes.VoiceIntentBody(text="hello"), _principal()
    )
    assert result.reply == "answer" and result.understood
    run = await setup.container.run_store.get_run(result.run_id)
    assert run.status is RunStatus.COMPLETED
    assert (run.actor_principal_id, run.workspace_id, run.project_id) == (
        _ACTOR,
        _WORKSPACE,
        setup.project_id,
    )
    assert len(setup.requests) == 1
    assert "tools" not in json.loads(setup.requests[0].content)


async def test_missing_runtime_fails_closed_instead_of_returning_stub_success(
    setup: Setup, monkeypatch
):
    monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace())
    with pytest.raises(GovernedModelFailure):
        chat.build_llm_port()
    assert setup.requests == []


async def test_public_complete_error_is_not_success_content(setup: Setup):
    setup.responses = [httpx.ReadTimeout("unknown")]
    with pytest.raises(GovernedModelFailure):
        await chat_routes.complete(_request(workspace_id=_WORKSPACE), _principal())
    (run,) = await setup.container.run_store.list_by_status(
        RunStatus.FAILED, workspace_id=_WORKSPACE
    )
    assert run.result is None
    assert len(setup.requests) == 1


async def test_completed_tool_correction_has_distinct_stable_effect_key(setup: Setup):
    identity = await _running(setup)
    setup.responses = [_sse("Please poll_jira for tasks"), _body("corrected answer")]
    with _context(identity):
        first = [
            event async for event in chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        ]
    later = await _later(setup, identity)
    with _context(later):
        second = [
            event async for event in chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        ]
    assert (
        first[-1]
        == second[-1]
        == {"type": "done", "content": "corrected answer", "model": "request-alias"}
    )
    assert len(setup.requests) == 2
    for key in ("hive-chat:turn:0", "hive-chat:turn:0:tool-correction"):
        (invocation,) = await _history(setup, identity, key)
        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.attempt_id == identity[2]


@pytest.mark.parametrize("stream", [False, True])
async def test_tool_continuations_and_final_synthesis_have_distinct_replayable_keys(
    setup: Setup, monkeypatch, stream: bool
):
    identity = await _running(setup)
    tool_call = {
        "id": "tool",
        "type": "function",
        "function": {"name": "profile_get", "arguments": "{}"},
    }
    if stream:
        frame = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, **tool_call}]},
                    "finish_reason": "tool_calls",
                }
            ]
        }
        scripted = f"data: {json.dumps(frame)}\n\ndata: [DONE]\n\n"
    else:
        scripted = _body("", [tool_call])
    setup.responses = [scripted] * 5 + [_body("final synthesis")]

    async def tool(*args, **kwargs):
        return {"profile": {}}, "profile"

    monkeypatch.setattr(chat, "_gated_execute_tool", tool)

    async def call():
        if stream:
            events = [
                event
                async for event in chat.run_chat_completion_streaming(
                    _request(max_tokens=31), user_id=_ACTOR
                )
            ]
            return events[-1]["content"]
        response = await chat.run_chat_completion(_request(max_tokens=31), user_id=_ACTOR)
        return response["choices"][0]["message"]["content"]

    with _context(identity):
        assert await call() == "final synthesis"
    later = await _later(setup, identity)
    with _context(later):
        assert await call() == "final synthesis"
    assert len(setup.requests) == 6
    for key in [*(f"hive-chat:turn:{index}" for index in range(5)), "hive-chat:synthesis"]:
        (invocation,) = await _history(setup, identity, key)
        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.attempt_id == identity[2]
    assert "tools" not in json.loads(setup.requests[-1].content)
    assert all(json.loads(sent.content)["max_tokens"] == 31 for sent in setup.requests)


async def test_unknown_dashboard_analysis_blocks_continuation_and_later_attempt(
    setup: Setup, monkeypatch
):
    identity = await _running(setup)
    tool_call = {
        "id": "tool",
        "type": "function",
        "function": {"name": "analyze_dashboard", "arguments": "{}"},
    }
    setup.responses = [_body("", [tool_call]), httpx.ReadTimeout("vision unknown")]

    # Keep the real error wrapper in _gated_execute_tool; substitute only its
    # non-model tool dispatch, so a swallowed UNKNOWN would continue the loop.
    async def tool(name, args, user_id, **kwargs):
        return await chat._tool_analyze_dashboard(args, user_id, None)

    monkeypatch.setattr(chat, "_execute_tool", tool)
    with _context(identity), pytest.raises(GovernedModelFailure):
        await chat.run_chat_completion(_request(), user_id=_ACTOR)
    later = await _later(setup, identity)
    with _context(later), pytest.raises(GovernedModelFailure):
        await chat.run_chat_completion(_request(), user_id=_ACTOR)
    assert len(setup.requests) == 2
    (invocation,) = await _history(setup, identity, "hive-chat:turn:0:tool:0:dashboard-analysis")
    assert invocation.status is InvocationStatus.UNKNOWN
    assert await _history(setup, identity, "hive-chat:turn:1") == []


async def test_closing_internal_stream_settles_unknown_before_return_and_blocks_replay(
    setup: Setup,
):
    import asyncio

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"index":0,"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
            await asyncio.Event().wait()

    identity = await _running(setup)
    setup.responses = [
        httpx.Response(
            200, stream=InterruptedStream(), headers={"content-type": "text/event-stream"}
        )
    ]
    with _context(identity):
        events = chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        assert (await anext(events))["type"] == "status"
        assert (await anext(events)) == {"type": "delta", "content": "partial"}
        await events.aclose()
    (invocation,) = await _history(setup, identity)
    assert invocation.status is InvocationStatus.UNKNOWN
    later = await _later(setup, identity)
    with _context(later), pytest.raises(GovernedModelFailure):
        _ = [
            event async for event in chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        ]
    assert len(setup.requests) == 1


@pytest.mark.parametrize("excluded", [False, True])
async def test_vision_keeps_chat_protocol_without_evading_declared_ingresses(
    setup: Setup, monkeypatch, excluded: bool
):
    from dataclasses import replace

    monkeypatch.setattr(get_settings(), "llm_http_variant", "responses")
    identity = await _running(setup)
    if excluded:
        metadata = await setup.container.provider_registry.get_model(_MODEL)
        setup.container.provider_registry.register_model(
            replace(metadata, supported_ingresses=("responses",))
        )
    with _context(identity):
        if excluded:
            with pytest.raises(GovernedModelFailure):
                await chat._tool_analyze_dashboard({"api_variant": "responses"}, _ACTOR, None)
        else:
            result = await chat._tool_analyze_dashboard({"api_variant": "responses"}, _ACTOR, None)
            assert result["analysis"] == "answer"
    assert len(setup.requests) == (0 if excluded else 1)
    if not excluded:
        assert setup.requests[0].url.path == "/v1/chat/completions"


async def test_review_multi_tool_stream_replay_preserves_positions(setup: Setup, monkeypatch):
    identity = await _running(setup)
    calls = [
        {
            "index": 0,
            "id": "read",
            "type": "function",
            "function": {"name": "profile_get", "arguments": "{}"},
        },
        {
            "index": 1,
            "id": "vision",
            "type": "function",
            "function": {"name": "analyze_dashboard", "arguments": "{}"},
        },
    ]
    frame = {
        "choices": [{"index": 0, "delta": {"tool_calls": calls}, "finish_reason": "tool_calls"}]
    }
    setup.responses = [
        f"data: {json.dumps(frame)}\n\ndata: [DONE]\n\n",
        _body("vision"),
        _sse("summary"),
    ]
    dispatched = []

    async def tool(name, args, user_id, gate_id, **kwargs):
        dispatched.append(name)
        if name == "analyze_dashboard":
            return await chat._tool_analyze_dashboard(args, user_id, None), "analyzed"
        return {"profile": {}}, "profile"

    monkeypatch.setattr(chat, "_gated_execute_tool", tool)
    with _context(identity):
        first = [
            event async for event in chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        ]
    assert dispatched == ["profile_get", "analyze_dashboard"]
    assert len(setup.requests) == 3
    dispatched.clear()
    later = await _later(setup, identity)
    with _context(later):
        second = [
            event async for event in chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        ]
    assert first[-1] == second[-1]
    assert len(setup.requests) == 3, (dispatched, [r.url.path for r in setup.requests])
    assert dispatched == ["profile_get", "analyze_dashboard"]


async def test_review_multi_tool_replay_cannot_escape_unknown_vision(setup: Setup, monkeypatch):
    identity = await _running(setup)
    calls = [
        {
            "index": 0,
            "id": "read",
            "type": "function",
            "function": {"name": "profile_get", "arguments": "{}"},
        },
        {
            "index": 1,
            "id": "vision",
            "type": "function",
            "function": {"name": "analyze_dashboard", "arguments": "{}"},
        },
    ]
    frame = {
        "choices": [{"index": 0, "delta": {"tool_calls": calls}, "finish_reason": "tool_calls"}]
    }
    setup.responses = [
        f"data: {json.dumps(frame)}\n\ndata: [DONE]\n\n",
        httpx.ReadTimeout("vision unknown"),
    ]

    async def tool(name, args, user_id, gate_id, **kwargs):
        if name == "analyze_dashboard":
            return await chat._tool_analyze_dashboard(args, user_id, None), "analyzed"
        return {"profile": {}}, "profile"

    monkeypatch.setattr(chat, "_gated_execute_tool", tool)
    with _context(identity), pytest.raises(GovernedModelFailure):
        _ = [
            event async for event in chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        ]
    prior = await _history(setup, identity, "hive-chat:turn:0:tool:1:dashboard-analysis")
    assert prior[0].status is InvocationStatus.UNKNOWN
    assert len(setup.requests) == 2
    later = await _later(setup, identity)
    setup.responses = [_body("duplicate vision"), _sse("summary")]
    with _context(later), pytest.raises(GovernedModelFailure):
        _ = [
            event async for event in chat.run_chat_completion_streaming(_request(), user_id=_ACTOR)
        ]
    assert len(setup.requests) == 2
