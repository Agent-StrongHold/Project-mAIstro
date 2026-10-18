"""Materialized agents preserve admitted authority and the configured wire contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from adapters.maistro_core import _construct_runtime
from config import Settings
from models.schemas import Agent
from services.agent_materialization import RuntimeSource, _build_runtime_agent
from tests._admitted_model_fixture import setup

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    GatewayEndpoint,
)
from maistro.credentials.types import CredentialRecord
from maistro.http import set_test_transport
from maistro.observability.correlation import bind_execution_context
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata
from maistro.runs.store import RunIntegrityError
from maistro.types.config import ModelBindingConfig


@pytest.fixture(autouse=True)
def isolated_transport():
    yield
    set_test_transport(None)


async def materialized(
    monkeypatch,
    tmp_path,
    *,
    workspace="workspace",
    api_base="https://gateway.fixture/v1",
    **setup_options,
):
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="gpt-5",
                provider="fixture",
                cost_per_1k_input=0.1,
                cost_per_1k_output=0.1,
                latency_p50_ms=10,
            )
        ]
    )
    s = await setup(registry=registry, **setup_options)
    # A second scope's credential must never become ambient authority.
    s.effects.credentials.add(
        workspace_id="default",
        project_id="agent-runtime",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="wrong-workspace-key",
        ),
    )
    container = SimpleNamespace(
        agents={},
        prompt_manager=SimpleNamespace(upsert=AsyncMock()),
        capability_effects=s.effects,
        provider_registry=registry,
        llm_router=CostAwareRouter(registry),
        run_store=s.runs,
        **{
            name: object()
            for name in (
                "context_builder",
                "warden",
                "sentinel",
                "learning_store",
                "context_assembly_policy",
                "learning_extractor",
                "outcome_store",
                "session_store",
                "quota_tracker",
                "a2a_delegator",
            )
        },
    )

    async def container_for(config):
        container.config = config
        return container

    # Boot factory wiring is checked separately; this test retains the actual
    # runtime constructor and actual definition-to-Agent construction.
    async def boot_agents(**kwargs):
        return {}

    monkeypatch.setattr("maistro.container.create_container", container_for)
    monkeypatch.setattr("maistro.agents.factory.create_agents", boot_agents)
    monkeypatch.setattr("services.secrets.maistro_llm_api_key", lambda settings: "fixture-key")
    monkeypatch.setattr("maistro.config.database.resolve_database_url", lambda: "")
    runtime = await _construct_runtime(
        Settings(
            maistro_agents_dir=str(tmp_path),
            litellm_api_base=api_base,
            hive_default_workspace_id="default",
            maistro_model_bindings=[
                ModelBindingConfig(
                    binding_id="declared", workspace_id="workspace", project_id=s.project_id
                )
            ]
            if setup_options.get("bindings", True)
            else [],
        )
    )
    definition = Agent(
        id="forge-probe",
        name="forge-probe",
        workspace_id=workspace,
        description="fixture",
        model="gpt-5",
        status="idle",
        created_at=datetime.now(UTC),
    )
    agent = await _build_runtime_agent(
        definition, RuntimeSource(container=container, llm=runtime.llm, preamble="")
    )
    return s, agent


@pytest.fixture(params=["complete", "stream"])
def model_call(request):
    async def call(s, agent, **kwargs):
        with bind_execution_context(
            run_id=s.identity[0], node_run_id=s.identity[1], attempt_id=s.identity[2]
        ):
            if request.param == "complete":
                return await agent._llm.complete(
                    [{"role": "user", "content": "hello"}], "gpt-5", **kwargs
                )

            def transport(http_request):
                s.sent.append(http_request)
                chunks = [
                    {"choices": [{"index": 0, "delta": {"content": "answer"}}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                    {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
                ]
                body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
                return httpx.Response(200, content=(body + "data: [DONE]\n\n").encode())

            set_test_transport(httpx.MockTransport(transport))
            return [
                chunk
                async for chunk in agent._llm.stream(
                    [{"role": "user", "content": "hello"}], "gpt-5", **kwargs
                )
            ]

    return call


async def assert_no_model_effect(s, earlier_usage):
    assert s.sent == []
    assert not await s.effects.invocation_store.list_effect(
        run_id=s.identity[0],
        node_run_id=s.identity[1],
        binding_id="declared",
        effect_key="agent-llm-1",
    )
    assert s.effects.usage_log.events_for("gpt-5") == earlier_usage


@pytest.mark.parametrize("workspace", ["workspace", None])
async def test_materialized_agent_uses_persisted_scope_actor_and_operator_binding(
    monkeypatch, tmp_path, workspace, model_call
):
    s, agent = await materialized(monkeypatch, tmp_path, workspace=workspace)
    await model_call(s, agent)
    rows = await s.effects.invocation_store.list_effect(
        run_id=s.identity[0],
        node_run_id=s.identity[1],
        binding_id="declared",
        effect_key="agent-llm-1",
    )
    assert len(rows) == 1
    row = rows[0]
    assert (row.workspace_id, row.project_id, row.actor_id) == (
        "workspace",
        s.project_id,
        "admitted-actor",
    )
    assert (row.run_id, row.node_run_id, row.attempt_id) == s.identity
    assert row.binding.credential_refs == (DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,)
    assert s.sent[0].headers["Authorization"] == "Bearer fixture-key"
    assert row.status is InvocationStatus.COMPLETED
    assert row.usage.input_units == 7
    assert row.usage.output_units == 3
    events = [
        event
        for event in s.effects.usage_log.events_for("gpt-5")
        if event.invocation_id == row.invocation_id
    ]
    assert len(events) == 1


async def test_definition_workspace_is_a_restriction_not_authority(
    monkeypatch, tmp_path, model_call
):
    s, agent = await materialized(monkeypatch, tmp_path, workspace="foreign")
    earlier_usage = s.effects.usage_log.events_for("gpt-5")
    with pytest.raises(RunIntegrityError, match="workspace"):
        await model_call(s, agent)
    await assert_no_model_effect(s, earlier_usage)


@pytest.mark.parametrize(
    "options,revoked", [({"bindings": False}, False), ({"disabled": True}, False), ({}, True)]
)
async def test_materialized_agent_refuses_missing_disabled_or_revoked_binding(
    monkeypatch, tmp_path, options, revoked, model_call
):
    s, agent = await materialized(monkeypatch, tmp_path, **options)
    if revoked:
        await s.effects.bindings.revoke("declared")
    earlier_usage = s.effects.usage_log.events_for("gpt-5")
    with pytest.raises(BindingResolutionError):
        await model_call(s, agent)
    await assert_no_model_effect(s, earlier_usage)


async def test_materialized_agent_requires_real_live_attempt_lease(
    monkeypatch, tmp_path, model_call
):
    s, agent = await materialized(monkeypatch, tmp_path, leased=False)
    earlier_usage = s.effects.usage_log.events_for("gpt-5")
    with pytest.raises(RunIntegrityError, match="lease"):
        await model_call(s, agent)
    await assert_no_model_effect(s, earlier_usage)


@pytest.mark.parametrize("temperature", [None, 0.0, 0.3])
async def test_materialized_sampling_preserves_omission_and_explicit_values(
    monkeypatch, tmp_path, temperature, model_call
):
    s, agent = await materialized(monkeypatch, tmp_path)
    await model_call(s, agent, **({} if temperature is None else {"temperature": temperature}))
    payload = json.loads(s.sent[0].content)
    if temperature is None:
        assert "temperature" not in payload
    else:
        assert payload["temperature"] == temperature


@pytest.mark.parametrize(
    "base",
    [
        "https://gateway.fixture/openai",
        "https://gateway.fixture/openai/",
        "https://gateway.fixture/v1",
        "https://gateway.fixture",
    ],
)
async def test_materialized_client_preserves_configured_api_base(
    monkeypatch, tmp_path, base, model_call
):
    s, agent = await materialized(monkeypatch, tmp_path, api_base=base)
    await model_call(s, agent)
    assert str(s.sent[0].url) == base.rstrip("/") + "/chat/completions"


def test_gateway_root_callers_keep_v1_normalization():
    assert GatewayEndpoint(base_url="https://gateway.fixture")._base == "https://gateway.fixture/v1"


async def test_distinct_agents_do_not_replay_each_others_completion(monkeypatch, tmp_path):
    from maistro.capabilities.model_chat import GovernedLLMClient

    s, agent = await materialized(monkeypatch, tmp_path)
    other = GovernedLLMClient(agent._llm._calls, workspace_id="workspace")
    with bind_execution_context(
        run_id=s.identity[0], node_run_id=s.identity[1], attempt_id=s.identity[2]
    ):
        agent._llm.set_turn(agent_name="first-agent")
        await agent._llm.complete([{"role": "user", "content": "first"}], "gpt-5")
        other.set_turn(agent_name="second-agent")
        await other.complete([{"role": "user", "content": "second"}], "gpt-5")
    assert len(s.sent) == 2
    assert [json.loads(request.content)["messages"][0]["content"] for request in s.sent] == [
        "first",
        "second",
    ]


async def test_tail_delegation_revisit_is_distinct_and_same_visit_replays(monkeypatch, tmp_path):
    s, agent = await materialized(monkeypatch, tmp_path)
    with bind_execution_context(
        run_id=s.identity[0], node_run_id=s.identity[1], attempt_id=s.identity[2]
    ):
        for depth, content in [(0, "first visit"), (1, "revisit"), (1, "revisit")]:
            agent._llm.set_agent_turn(agent_name=agent.identity.name, delegation_depth=depth)
            await agent._llm.complete([{"role": "user", "content": content}], "gpt-5")
    assert len(s.sent) == 2
    assert [json.loads(request.content)["messages"][0]["content"] for request in s.sent] == [
        "first visit",
        "revisit",
    ]


@pytest.mark.parametrize("workspace", ["", " "])
async def test_only_none_definition_scope_is_unrestricted(
    monkeypatch, tmp_path, workspace, model_call
):
    s, agent = await materialized(monkeypatch, tmp_path, workspace=workspace)
    earlier_usage = s.effects.usage_log.events_for("gpt-5")
    with pytest.raises(RunIntegrityError, match="workspace"):
        await model_call(s, agent)
    await assert_no_model_effect(s, earlier_usage)


async def test_materialized_client_rechecks_revocation_before_replay(
    monkeypatch, tmp_path, model_call
):
    s, agent = await materialized(monkeypatch, tmp_path)
    await model_call(s, agent)
    assert len(s.sent) == 1
    await s.effects.bindings.revoke("declared")
    agent._llm.clear_turn()
    earlier_usage = s.effects.usage_log.events_for("gpt-5")
    with pytest.raises(BindingResolutionError):
        await model_call(s, agent)
    assert len(s.sent) == 1
    assert s.effects.usage_log.events_for("gpt-5") == earlier_usage
