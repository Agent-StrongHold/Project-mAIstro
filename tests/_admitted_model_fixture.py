"""Shared canonical model-admission fixture; only the final HTTP is substituted."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx

from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.model_binding_bootstrap import bootstrap_model_bindings
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.graph.definitions import Graph, Node
from maistro.http import set_test_transport
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.types.config import AgentConfig, ModelBindingConfig


@dataclass
class Setup:
    calls: AdmittedModelCalls
    effects: Any
    runs: InMemoryRunStore
    identity: tuple[str, str, str]
    sent: list[httpx.Request]
    project_id: str
    fencing_token: str | None


async def setup(
    *,
    bindings: bool = True,
    key: str = "fixture-key",
    disabled: bool = False,
    leased: bool = True,
    effects: CapabilityEffectContext | None = None,
    registry: InMemoryProviderRegistry | None = None,
) -> Setup:
    scope = InMemoryProjectScopeStore()
    project = await scope.create_root("workspace")
    runs = InMemoryRunStore(project_store=scope)
    graph = Graph(
        name="admitted-model-test",
        workspace_id="workspace",
        project_id=project.project_id,
        nodes=[Node(node_id="chat", node_type="chat", name="chat")],
    )
    run = await runs.create_run(
        graph, actor_principal_id="admitted-actor", initial_status=RunStatus.QUEUED
    )
    await runs.transition_run(run.run_id, RunStatus.RUNNING)
    node = await runs.create_node_run(run.run_id, node_id="chat")
    for step in transition_path(node.status, RunStatus.RUNNING):
        node = await runs.transition_node_run(node.node_run_id, step)
    attempt = await runs.create_attempt(
        node.node_run_id,
        lease_holder="fixture-worker" if leased else None,
        lease_ttl=timedelta(minutes=30),
    )
    token = attempt.execution_lease.fencing_token if attempt.execution_lease else None
    await runs.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token)
    effects = (
        effects
        if effects is not None
        else new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    )
    config = AgentConfig(
        workspace_id="workspace",
        litellm_key=key,
        model_bindings=[
            ModelBindingConfig(
                binding_id="declared", project_id=project.project_id, disabled=disabled
            )
        ]
        if bindings
        else [],
    )
    await bootstrap_model_bindings(config, effects)
    registry = registry if registry is not None else InMemoryProviderRegistry()
    sent: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "model": "request-alias",
                "choices": [{"message": {"role": "assistant", "content": "answer"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    set_test_transport(httpx.MockTransport(transport))
    calls = AdmittedModelCalls(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(
            base_url="http://gateway.fixture", api_key="never-use-endpoint-key"
        ),
        run_store=runs,
        binding_ids=tuple(b.binding_id for b in config.model_bindings),
    )
    return Setup(
        calls,
        effects,
        runs,
        (run.run_id, node.node_run_id, attempt.attempt_id),
        sent,
        project.project_id,
        token,
    )
