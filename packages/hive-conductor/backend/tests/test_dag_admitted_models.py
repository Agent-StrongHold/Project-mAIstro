"""#1085: shipped ordinary DAG dispatch, real SQLite authority, final HTTP fake."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from services import canonical_dag_runner as runner
from services.dag_execution_scope import DagExecutionScope
from services.engine import get_engine
from services.governed_model import dag_node_model_calls
from services.legacy_dag_node import _run_llm_node

from maistro.capabilities.invocation import InvocationStatus
from maistro.container import Container, create_container
from maistro.graph.nodes.base import NodeContext
from maistro.http import set_test_transport
from maistro.observability.correlation import bind_execution_context
from maistro.policy.types import Decision, PolicyVerdict
from maistro.providers.types import ModelMetadata
from maistro.quota.invocation_quota import QuotaBudget
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.types.config import AgentConfig, ModelBindingConfig

_WORKSPACE = "dag-model-workspace"
_ACTOR = "dag-model-actor"
_BINDING = "dag-model-binding"
_MODEL = "configured-model"


@dataclass
class Setup:
    container: Container
    path: Path
    project_id: str
    requests: list[httpx.Request] = field(default_factory=list)
    body: dict[str, Any] = field(
        default_factory=lambda: {
            "model": "response-version",
            "choices": [{"message": {"content": '{"done":true}'}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }
    )
    fail_transport: bool = False

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
    initial = await create_container(
        AgentConfig(database_url=database_url, router_api_key="test-router-key")
    )
    await initial.workspace_store.create(
        name="DAG models", creator_user_id=_ACTOR, workspace_id=_WORKSPACE
    )
    project = await initial.project_scope_store.root_for_workspace(_WORKSPACE)
    await initial.aclose()
    bindings = [
        {
            "binding_id": options.get("binding_id", _BINDING),
            "project_id": project.project_id,
            "provider_name": options.get("pin", _MODEL),
        },
        {"binding_id": "foreign-project", "project_id": "foreign", "provider_name": _MODEL},
        {"binding_id": "foreign-node", "project_id": project.project_id, "node_id": "other"},
    ]
    if options.get("ambiguous"):
        bindings.append({"binding_id": "second", "project_id": project.project_id})
    if options.get("unconfigured"):
        bindings = []
    owner = await create_container(
        AgentConfig(
            router_api_key="test-router-key",
            database_url=database_url,
            workspace_id=_WORKSPACE,
            provider_config_path=str(providers),
            litellm_url="https://configured.gateway.test",
            litellm_key="" if options.get("missing_key") else "scoped-test-key",
            model_bindings=bindings,
        )
    )
    # Only install the selected Container, just as the embedded bridge does.
    monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=owner))
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://ambient.must-not-win.test")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "ambient-key-must-not-be-borrowed")
    monkeypatch.setenv("LITELLM_API_BASE", "https://raw.must-not-run.test")
    monkeypatch.setenv("LITELLM_API_KEY", "raw-key-must-not-be-borrowed")
    state = Setup(owner, path, project.project_id)

    def transport(http_request: httpx.Request) -> httpx.Response:
        state.requests.append(http_request)
        if state.fail_transport:
            raise httpx.ReadTimeout("provider completion unknown", request=http_request)
        return httpx.Response(200, json=state.body)

    published_effects = owner.capability_effects
    set_test_transport(httpx.MockTransport(transport))
    try:
        yield state
    finally:
        set_test_transport(None)
        # Policy-refusal cases temporarily narrow this field. Container close
        # must withdraw the exact context it published, not the test replacement.
        owner.capability_effects = published_effects
        await owner.aclose()


def _dag(binding_id: str = _BINDING) -> dict[str, Any]:
    return {
        "id": "admitted-dag",
        "name": "Ordinary model proof",
        "description": "perform work",
        "nodes": [
            {
                "id": "model-node",
                "role": "worker",
                "model": "request-alias",
                "prompt": "respond with JSON",
                "model_binding_id": binding_id,
                "config": {"execution_tier": "safe", "timeout_s": 17},
            }
        ],
        "edges": [],
        "entry_node": "model-node",
    }


async def _execute(s: Setup, dag: dict[str, Any] | None = None) -> dict[str, Any]:
    def no_raw_builder(*args: Any) -> Any:
        raise AssertionError("ordinary DAG must never use an injected raw builder")

    def no_usage_hook(*args: Any) -> None:
        raise AssertionError("canonical Invocation owns ordinary model usage exactly once")

    return await runner.execute_dag(
        dag or _dag(),
        scope=DagExecutionScope(workspace_id=_WORKSPACE, project_id=s.project_id, user_id=_ACTOR),
        llm_builder=no_raw_builder,
        on_response=no_usage_hook,
    )


async def _evidence(s: Setup, run_id: str) -> tuple[Any, Any, list[Any]]:
    nodes = await s.container.run_store.list_node_runs(run_id)
    assert len(nodes) == 1
    attempts = await s.container.run_store.list_attempts(nodes[0].node_run_id)
    assert len(attempts) == 1
    invocations = await s.container.invocation_store.list_effect(
        run_id=run_id,
        node_run_id=nodes[0].node_run_id,
        binding_id=_BINDING,
        effect_key="dag:model",
    )
    return nodes[0], attempts[0], invocations


@pytest.mark.parametrize("placement", ["top-level", "config", "unambiguous"])
async def test_shipped_dag_joins_authority_usage_pin_and_timeout(
    setup: Setup, placement: str
) -> None:
    dag = _dag()
    if placement == "top-level":
        dag["nodes"][0]["config"]["model_binding_id"] = "foreign-project"
    elif placement == "config":
        dag["nodes"][0]["config"]["model_binding_id"] = dag["nodes"][0].pop("model_binding_id")
    elif placement == "unambiguous":
        dag["nodes"][0].pop("model_binding_id")
    before = setup.grants()
    result = await _execute(setup, dag)
    assert result["status"] == "completed", result
    assert result["node_results"]["model-node"] == {
        "role": "worker",
        "response": '{"done":true}',
        "success": True,
        "model": "request-alias",
    }
    node, attempt, invocations = await _evidence(setup, result["run_id"])
    run = await setup.container.run_store.get_run(result["run_id"])
    assert run.status is node.status is RunStatus.COMPLETED
    assert attempt.status is AttemptStatus.COMPLETED
    assert attempt.execution_lease is not None
    assert len(invocations) == len(setup.requests) == 1
    invocation = invocations[0]
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.actor_id == run.actor_principal_id == _ACTOR
    assert (invocation.run_id, invocation.node_run_id, invocation.attempt_id) == (
        run.run_id,
        node.node_run_id,
        attempt.attempt_id,
    )
    declared = await setup.container.capability_effects.bindings.get(_BINDING)
    assert declared is not None
    shared = {
        "binding_id",
        "workspace_id",
        "project_id",
        "node_id",
        "capability",
        "provider_name",
        "credential_refs",
        "policy_refs",
        "config",
    }
    assert invocation.binding.model_dump(include=shared) == declared.model_dump(include=shared)
    assert (invocation.binding.workspace_id, invocation.binding.project_id) == (
        _WORKSPACE,
        setup.project_id,
    )
    assert invocation.usage.model == _MODEL
    assert invocation.usage.cost_cents == 2.0
    events = [
        event
        for event in setup.container.usage_log.events_for(_MODEL)
        if event.invocation_id == invocation.invocation_id
    ]
    assert len(events) == 1
    assert (events[0].input_tokens, events[0].output_tokens, events[0].usage_reported) == (
        1000,
        500,
        True,
    )
    request = setup.requests[0]
    assert str(request.url) == "https://configured.gateway.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer scoped-test-key"
    assert request.extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), 17.0
    )
    payload = json.loads(request.content)
    assert payload["model"] == _MODEL
    assert payload["temperature"] == 0.3
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"] == [
        {"role": "system", "content": "respond with JSON"},
        {"role": "user", "content": "Task: perform work"},
    ]
    assert setup.grants() == before


@pytest.mark.parametrize(
    "refusal", ["missing", "revoked", "disabled", "foreign-project", "foreign-node", "undeclared"]
)
async def test_binding_refusals_never_dispatch_or_grant(setup: Setup, refusal: str) -> None:
    bindings = setup.container.capability_effects.bindings
    selected = _BINDING
    if refusal == "missing":
        setup.container.config.model_bindings.append(
            ModelBindingConfig(binding_id="missing", project_id=setup.project_id)
        )
        selected = "missing"
    elif refusal == "revoked":
        await bindings.revoke(_BINDING)
    elif refusal == "disabled":
        # Operator config supplies this immutable disabled grant before calling.
        source = await bindings.get(_BINDING)
        await bindings.put(source.model_copy(update={"binding_id": "disabled", "disabled": True}))
        setup.container.config.model_bindings.append(
            ModelBindingConfig(binding_id="disabled", project_id=setup.project_id, disabled=True)
        )
        selected = "disabled"
    elif refusal == "undeclared":
        source = await bindings.get(_BINDING)
        await bindings.put(source.model_copy(update={"binding_id": "stored-but-undeclared"}))
        selected = "stored-but-undeclared"
    else:
        selected = refusal
    before = setup.grants()
    dag = _dag(selected)
    dag["nodes"][0]["config"]["model_binding_id"] = _BINDING
    result = await _execute(setup, dag)
    assert result["status"] == "failed", result
    assert setup.requests == []
    assert setup.grants() == before
    node, attempt, invocations = await _evidence(setup, result["run_id"])
    assert node.status is RunStatus.FAILED
    assert attempt.result["status"] == "failed"
    assert invocations == []


@pytest.mark.parametrize(
    "setup", [{"ambiguous": True}, {"unconfigured": True}, {"missing_key": True}], indirect=True
)
async def test_config_refusals_cannot_borrow_ambient_keys(setup: Setup) -> None:
    before = setup.grants()
    stats = setup.container.capability_effects.credentials.stats(
        workspace_id=_WORKSPACE, project_id=setup.project_id, provider="litellm"
    )
    result = await _execute(setup, _dag(""))
    assert result["status"] == "failed", result
    assert setup.requests == []
    assert setup.grants() == before
    assert (
        setup.container.capability_effects.credentials.stats(
            workspace_id=_WORKSPACE, project_id=setup.project_id, provider="litellm"
        )
        == stats
    )


@pytest.mark.parametrize("refusal", ["policy", "requests", "tokens", "micro_usd"])
async def test_policy_and_actor_quota_deny_before_http_without_new_grants(
    setup: Setup, refusal: str
) -> None:
    if refusal == "policy":

        async def deny(*args: Any) -> PolicyVerdict:
            return PolicyVerdict(Decision.DENY, reason="test policy refusal", rule="test")

        setup.container.capability_effects = (
            setup.container.capability_effects.with_policy_evaluator(deny)
        )
    else:
        await setup.container.capability_effects.quota.register_budget(
            QuotaBudget(
                budget_id="actor-budget",
                unit=refusal,
                limit=0 if refusal == "requests" else 100000,
                period_start=0,
                period_end=2**62,
                coverage_ref="test-opening",
                opening_spend=0,
                workspace_id=_WORKSPACE,
                principal_id=_ACTOR,
                capability="model.chat",
            )
        )
    before = setup.grants()
    result = await _execute(setup)
    assert result["status"] == "failed", result
    assert setup.requests == []
    assert setup.grants() == before
    expected = {
        "policy": "policy",
        "requests": "quota",
        "tokens": "missing upper bound",
        "micro_usd": "missing upper bound",
    }
    assert expected[refusal] in result["error"].lower()


@pytest.mark.parametrize("missing", ["runtime", "context", "identity"])
async def test_missing_admission_cannot_use_raw_builder(setup: Setup, missing: str) -> None:
    runtime = dag_node_model_calls(setup.container)
    ctx = NodeContext(run_id="fake-run", dag_id="fake-dag", node_id="model-node")
    results: dict[str, dict[str, Any]] = {}
    before = setup.grants()
    await _run_llm_node(
        _dag()["nodes"][0],
        "model-node",
        {},
        results,
        "work",
        llm_builder=lambda *_: pytest.fail("raw model bypass"),
        ctx=None if missing == "context" else ctx,
        model_calls=None if missing == "runtime" else runtime,
    )
    assert results["model-node"]["success"] is False
    assert setup.requests == []
    assert setup.grants() == before


async def _running_context(s: Setup, *, leased: bool = True) -> NodeContext:
    graph = runner.graph_from_legacy_dag(_dag(), workspace_id=_WORKSPACE, project_id=s.project_id)
    runs = s.container.run_store
    run = await runs.create_run(graph, initial_status=RunStatus.QUEUED, actor_principal_id=_ACTOR)
    await runs.transition_run(run.run_id, RunStatus.RUNNING)
    node = await runs.create_node_run(run.run_id, node_id="model-node")
    for step in transition_path(node.status, RunStatus.RUNNING):
        node = await runs.transition_node_run(node.node_run_id, step)
    attempt = await runs.create_attempt(
        node.node_run_id,
        lease_holder="test-worker" if leased else None,
        lease_ttl=timedelta(minutes=30),
    )
    await runs.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token if leased else None,
    )
    return NodeContext(
        run_id=run.run_id,
        dag_id=graph.graph_id,
        node_id=node.node_id,
        node_run_id=node.node_run_id,
        attempt_id=attempt.attempt_id,
        user_id="request-actor-must-not-win",
    )


async def _call(s: Setup, ctx: NodeContext) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    await _run_llm_node(
        _dag()["nodes"][0],
        "model-node",
        {},
        results,
        "work",
        ctx=ctx,
        model_calls=dag_node_model_calls(s.container),
    )
    return results["model-node"]


@pytest.mark.parametrize("unknown", [False, True])
async def test_later_attempt_replays_or_refuses_unknown_without_second_http(
    setup: Setup, unknown: bool
) -> None:
    ctx = await _running_context(setup)
    setup.fail_transport = unknown
    before = setup.grants()
    first = await _call(setup, ctx)
    assert first["success"] is not unknown
    runs = setup.container.run_store
    old = await runs.get_attempt(ctx.attempt_id)
    # Simulate physical failure after the model effect, before domain acceptance.
    await runs.transition_attempt(
        old.attempt_id, AttemptStatus.FAILED, fencing_token=old.execution_lease.fencing_token
    )
    later = await runs.create_attempt(ctx.node_run_id, lease_holder="later-worker")
    await runs.transition_attempt(
        later.attempt_id, AttemptStatus.RUNNING, fencing_token=later.execution_lease.fencing_token
    )
    later_ctx = ctx.model_copy(update={"attempt_id": later.attempt_id})
    second = await _call(setup, later_ctx)
    assert second["success"] is not unknown
    if unknown:
        assert "unknown" in second["response"].lower()
    else:
        assert second == first
    invocations = await setup.container.invocation_store.list_effect(
        run_id=ctx.run_id, node_run_id=ctx.node_run_id, binding_id=_BINDING, effect_key="dag:model"
    )
    assert len(invocations) == len(setup.requests) == 1
    assert invocations[0].actor_id == _ACTOR
    assert invocations[0].attempt_id == old.attempt_id
    assert invocations[0].status is (
        InvocationStatus.UNKNOWN if unknown else InvocationStatus.COMPLETED
    )
    events = [
        e
        for e in setup.container.usage_log.events_for(_MODEL)
        if e.invocation_id == invocations[0].invocation_id
    ]
    assert len(events) == (0 if unknown else 1)
    assert setup.grants() == before


@pytest.mark.parametrize(
    "refusal", ["unleased", "expired", "foreign-context", "foreign-tuple", "terminal"]
)
async def test_invalid_persisted_execution_fails_closed(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    ctx = await _running_context(setup, leased=refusal != "unleased")
    if refusal == "expired":
        import maistro.capabilities.admitted_model as admitted

        future = datetime.now(UTC) + timedelta(hours=1)

        class Clock:
            @staticmethod
            def now(tz: Any) -> datetime:
                return future

        monkeypatch.setattr(admitted, "datetime", Clock)
    if refusal == "foreign-tuple":
        other = await _running_context(setup)
        ctx = ctx.model_copy(update={"attempt_id": other.attempt_id})
    if refusal == "terminal":
        await setup.container.run_store.transition_run(ctx.run_id, RunStatus.CANCELLED)
    before = setup.grants()
    with bind_execution_context(
        run_id=ctx.run_id,
        node_run_id=ctx.node_run_id,
        attempt_id=ctx.attempt_id,
        workspace_id="foreign" if refusal == "foreign-context" else _WORKSPACE,
        project_id=setup.project_id,
    ):
        result = await _call(setup, ctx)
    assert result["success"] is False
    assert setup.requests == []
    assert setup.grants() == before


@pytest.mark.parametrize("choices", [None, [], [None], [{"message": {}}]])
async def test_malformed_provider_response_remains_a_failed_node(
    setup: Setup, choices: Any
) -> None:
    setup.body["choices"] = choices
    result = await _execute(setup)
    assert result["status"] == "failed", result
    assert "no content" in result["error"]
    assert len(setup.requests) == 1


@pytest.mark.parametrize("setup", [{"pin": "unknown-pin"}, {}], indirect=True)
async def test_unknown_or_unavailable_pin_does_not_fallback(setup: Setup) -> None:
    registry = setup.container.provider_registry
    binding = await setup.container.capability_effects.bindings.get(_BINDING)
    if binding.provider_name == _MODEL:
        registry.mark_unavailable(_MODEL)
    registry.register_model(
        ModelMetadata(
            name="available-alternative",
            provider="test",
            cost_per_1k_input=0,
            cost_per_1k_output=0,
            latency_p50_ms=1,
        )
    )
    assert registry.is_available("available-alternative")
    before = setup.grants()
    result = await _execute(setup)
    assert result["status"] == "failed", result
    assert "pinned model" in result["error"].lower()
    assert setup.requests == []
    assert setup.grants() == before


@pytest.mark.parametrize("setup", [{"pin": ""}], indirect=True)
@pytest.mark.parametrize("requested", ["request-alias", ""])
async def test_unpinned_binding_preserves_alias_or_router_selection(
    setup: Setup, requested: str
) -> None:
    dag = _dag()
    dag["nodes"][0]["model"] = requested
    result = await _execute(setup, dag)
    assert result["status"] == "completed", result
    assert json.loads(setup.requests[0].content)["model"] == (requested or _MODEL)
    binding = await setup.container.capability_effects.bindings.get(_BINDING)
    assert binding.provider_name == ""


async def test_cached_calls_cannot_outlive_revocation(setup: Setup) -> None:
    calls = dag_node_model_calls(setup.container)
    ctx = await _running_context(setup)
    await setup.container.capability_effects.bindings.revoke(_BINDING)
    before = setup.grants()
    results: dict[str, dict[str, Any]] = {}
    await _run_llm_node(
        _dag()["nodes"][0], "model-node", {}, results, "work", ctx=ctx, model_calls=calls
    )
    assert results["model-node"]["success"] is False
    assert setup.requests == []
    assert setup.grants() == before


async def test_actor_budget_is_charged_once_and_next_run_is_refused(setup: Setup) -> None:
    quota = setup.container.capability_effects.quota
    await quota.register_budget(
        QuotaBudget(
            budget_id="one-model-call",
            unit="requests",
            limit=1,
            period_start=0,
            period_end=2**62,
            coverage_ref="test-opening",
            opening_spend=0,
            workspace_id=_WORKSPACE,
            principal_id=_ACTOR,
            capability="model.chat",
        )
    )
    first = await _execute(setup)
    assert first["status"] == "completed", first
    second = await _execute(setup)
    assert second["status"] == "failed", second
    assert len(setup.requests) == 1
    balance = await quota.balance("one-model-call")
    assert balance.spent == 1
    assert balance.held == 0


async def test_recovery_resolver_uses_the_same_admitted_container(setup: Setup) -> None:
    ctx = await _running_context(setup)
    run = await setup.container.run_store.get_run(ctx.run_id)
    node = runner._recovery_resolver(run)("model-node", run.graph.materialize())
    output = await node._execute(node.input_schema(), ctx)
    assert output.response == '{"done":true}'
    assert len(setup.requests) == 1
    assert setup.requests[0].headers["Authorization"] == "Bearer scoped-test-key"
    invocations = await setup.container.invocation_store.list_effect(
        run_id=ctx.run_id,
        node_run_id=ctx.node_run_id,
        binding_id=_BINDING,
        effect_key="dag:model",
    )
    assert len(invocations) == 1
    assert invocations[0].actor_id == _ACTOR


@pytest.mark.parametrize("setup", [{"binding_id": "123"}], indirect=True)
@pytest.mark.parametrize(
    "invalid",
    [False, 0, [], {}, None, 123],
    ids=["false", "zero", "list", "object", "null", "integer"],
)
@pytest.mark.parametrize("placement", ["top-level", "top-with-config", "config", "config-with-top"])
async def test_malformed_binding_selectors_refuse_before_fallback(
    setup: Setup, invalid: Any, placement: str
) -> None:
    dag = _dag("123")
    raw = dag["nodes"][0]
    if placement.startswith("top"):
        raw["model_binding_id"] = invalid
        if placement == "top-with-config":
            raw["config"]["model_binding_id"] = "123"
    else:
        raw["config"]["model_binding_id"] = invalid
        if placement == "config":
            raw.pop("model_binding_id")
    before = setup.grants()
    result = await _execute(setup, dag)
    assert result["status"] == "failed", result
    assert "model_binding_id must be a string when provided" in result["error"]
    assert setup.requests == []
    assert setup.grants() == before
    nodes = await setup.container.run_store.list_node_runs(result["run_id"])
    assert len(nodes) == 1
    assert nodes[0].status is RunStatus.FAILED
    assert (
        await setup.container.invocation_store.list_effect(
            run_id=result["run_id"],
            node_run_id=nodes[0].node_run_id,
            binding_id="123",
            effect_key="dag:model",
        )
        == []
    )


@pytest.mark.parametrize("setup", [{"binding_id": "123"}], indirect=True)
@pytest.mark.parametrize(
    "selectors",
    [
        {"top": "123", "config": "foreign-project"},
        {"top": "", "config": "123"},
        {"config": "123"},
        {"top": "123"},
        {"top": "", "config": ""},
        {},
    ],
)
async def test_valid_string_selectors_keep_precedence_and_empty_fallback(
    setup: Setup, selectors: dict[str, str]
) -> None:
    dag = _dag()
    raw = dag["nodes"][0]
    raw.pop("model_binding_id")
    if "top" in selectors:
        raw["model_binding_id"] = selectors["top"]
    if "config" in selectors:
        raw["config"]["model_binding_id"] = selectors["config"]
    before = setup.grants()
    result = await _execute(setup, dag)
    assert result["status"] == "completed", result
    assert len(setup.requests) == 1
    assert setup.grants() == before
    nodes = await setup.container.run_store.list_node_runs(result["run_id"])
    invocations = await setup.container.invocation_store.list_effect(
        run_id=result["run_id"],
        node_run_id=nodes[0].node_run_id,
        binding_id="123",
        effect_key="dag:model",
    )
    assert len(invocations) == 1
    assert invocations[0].status is InvocationStatus.COMPLETED
