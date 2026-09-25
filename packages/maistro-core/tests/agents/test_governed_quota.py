from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from maistro.agents.base import Agent
from maistro.agents.strategies.direct import DirectStrategy
from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.model_chat import GovernedLLMClient
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    GatewayEndpoint,
)
from maistro.credentials.types import CredentialRecord
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.security.warden.detector import Warden
from maistro.types.agent import AgentIdentity


class _ContextBuilder:
    async def build(
        self, messages: list[dict[str, Any]], identity: Any, **kwargs: Any
    ) -> tuple[list[dict[str, Any]], list[int]]:
        return messages, []


class _PromptManager:
    pass


def _patch_gateway(monkeypatch: Any) -> None:
    body = {
        "model": "fast-model-v3",
        "choices": [{"message": {"role": "assistant", "content": "governed"}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return body

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def post(self, *args: Any, **kwargs: Any) -> _Response:
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


async def test_agent_completion_uses_canonical_invocation_quota_hook(
    monkeypatch: Any,
) -> None:
    _patch_gateway(monkeypatch)
    tracker = InMemoryQuotaTracker()
    usage_log = InMemoryUsageLog()
    effects = new_in_memory_effect_context(usage_log=usage_log, quota_tracker=tracker)
    # Binding-scoped credential routing (#1091): the governed call refuses
    # before any HTTP unless the credential the Binding authorizes exists in
    # its Workspace/Project scope. Register the deployment's default gateway
    # key exactly as bootstrap_model_bindings does in production.
    effects.credentials.add(
        workspace_id="ws-agent",
        project_id="agent-runtime",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="fast-model",
                provider="test-provider",
                cost_per_1k_input=0.5,
                cost_per_1k_output=1.0,
                latency_p50_ms=10,
            )
        ]
    )
    llm = GovernedLLMClient(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gateway"),
        workspace_id="ws-agent",
    )
    agent = Agent(
        AgentIdentity(name="writer", model="fast-model"),
        DirectStrategy(),
        llm=llm,
        context_builder=_ContextBuilder(),
        prompt_manager=_PromptManager(),
        warden=Warden(),
    )

    response = await agent.handle(
        [{"role": "user", "content": "say hello"}],
        SimpleNamespace(user_id="u1", org_id="o1", team_id="t1"),
        turn_id="run-agent-1",
    )

    assert response.content == "governed"
    events = usage_log.events_for("fast-model")
    assert len(events) == 1
    assert events[0].invocation_id is not None
    assert events[0].usage_reported is True
    assert events[0].provider == "fast-model"
    assert events[0].billing_cycle == "monthly"
    rows = await tracker.get_all_usage()
    assert rows[0]["total_tokens"] == 10
