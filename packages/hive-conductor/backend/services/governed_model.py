"""Hive composition for the canonical model Capability/Provider effect path.

This module is an application adapter, not a second model gateway. It obtains
maistro-core's container-owned Binding and Invocation authorities and exposes
small operations for shipped control-plane consumers. Secrets are accepted only
for the provider's transient registration call; health-check requests and
Invocation records contain no credential material. Authorization precedes every
HTTP effect: provider registration is Invocation-internal setup (#1088), and
evaluator/health invocations correlate to canonical Run/NodeRun/Attempt records
minted for the requesting operation, never to invented identifiers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.governed_invocation import (
    InvocationApprovalRequired,
    InvocationDenied,
)
from maistro.capabilities.model_chat import ModelCallResult, ModelChatEgress
from maistro.capabilities.providers.llm_gateway import (
    MODEL_CHAT_CAPABILITY,
    GatewayEndpoint,
    ModelChatRequest,
    ProviderRegistrationError,
    register_provider_models,
)
from maistro.graph.definitions import Graph, Node
from maistro.providers.protocols import LLMProviderRegistry, LLMRouter
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import (
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    RunStatus,
)


class ProviderActivationError(RuntimeError):
    """Provider registration failed before or during its health operation."""


class ProviderHealthError(RuntimeError):
    """The governed provider health Invocation failed."""


class ProviderAuthorizationError(PermissionError):
    """Canonical Binding/policy denied a provider health Invocation."""


@dataclass(frozen=True)
class GovernedModelRuntime:
    effects: CapabilityEffectContext
    registry: LLMProviderRegistry
    router: LLMRouter
    endpoint: GatewayEndpoint
    project_scope_store: Any | None = None
    run_store: Any | None = None


def _runtime() -> GovernedModelRuntime:
    """Return the live container authorities; fail closed without the bridge."""
    from services.engine import get_engine

    container = getattr(get_engine().agent_port, "container", None)
    if container is None:
        raise RuntimeError("canonical model egress is unavailable without the core Container")
    return GovernedModelRuntime(
        effects=container.capability_effects,
        registry=container.provider_registry,
        router=container.llm_router,
        endpoint=_endpoint(),
        project_scope_store=getattr(container, "project_scope_store", None),
        run_store=getattr(container, "run_store", None),
    )


def _endpoint() -> GatewayEndpoint:
    from config import get_settings

    settings = get_settings()
    base_url = (
        os.environ.get("MAISTRO_LLM_BASE_URL")
        or os.environ.get("LITELLM_PROXY_URL")
        or os.environ.get("LITELLM_API_BASE")
        or settings.litellm_api_base
        or ""
    ).strip()
    api_key = (
        os.environ.get("MAISTRO_LLM_API_KEY")
        or os.environ.get("LITELLM_API_KEY")
        or os.environ.get("LITELLM_PROXY_KEY")
        or os.environ.get("LITELLM_MASTER_KEY")
        or (
            settings.litellm_api_key.get_secret_value()
            if settings.litellm_api_key is not None
            else ""
        )
        or ""
    )
    if not base_url:
        raise ProviderActivationError("LLM gateway is not configured")
    return GatewayEndpoint(base_url=base_url, api_key=api_key)


def control_plane_binding(
    *, binding_id: str, workspace_id: str, project_id: str, provider_name: str = ""
) -> Binding:
    """Build the explicit operator-scoped Binding used by control-plane effects."""

    return Binding(
        binding_id=binding_id,
        workspace_id=workspace_id,
        project_id=project_id,
        node_id="control-plane",
        capability=MODEL_CHAT_CAPABILITY,
        provider_name=provider_name,
    )


async def ensure_binding(runtime: GovernedModelRuntime, binding: Binding) -> Binding:
    """Register an immutable control-plane Binding once, then reuse it."""

    existing = await runtime.effects.bindings.get(binding.binding_id)
    if existing is None:
        return await runtime.effects.bindings.put(binding)
    if existing != binding:
        raise BindingResolutionError(
            f"Binding {binding.binding_id!r} is immutable and does not match the request"
        )
    return existing


async def resolve_binding(
    runtime: GovernedModelRuntime,
    binding: Binding,
) -> Binding:
    """Resolve a control-plane Binding through the canonical scope authority."""

    return await runtime.effects.bindings.resolve(
        binding.binding_id,
        workspace_id=binding.workspace_id,
        project_id=binding.project_id,
        node_id=binding.node_id,
        capability=binding.capability,
    )


async def complete(
    *,
    runtime: GovernedModelRuntime,
    binding: Binding,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    effect_key: str,
    request: ModelChatRequest,
    setup: Any | None = None,
) -> ModelCallResult:
    """Execute a model request through canonical Binding -> Invocation.

    ``setup`` is Provider-internal preparation handed to the egress; it runs
    only after Binding scope resolution and policy authorization (#1088).
    """

    return await ModelChatEgress(
        runtime.effects,
        registry=runtime.registry,
        router=runtime.router,
        endpoint=runtime.endpoint,
    ).complete(
        binding=binding,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        effect_key=effect_key,
        request=request,
        setup=setup,
    )


async def register_and_health_check(
    *,
    runtime: GovernedModelRuntime,
    binding: Binding,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    provider_name: str,
    models: tuple[str, ...],
    api_key: str,
) -> ModelCallResult:
    """Run a provider's health check as one governed Invocation.

    Authorization precedes every HTTP effect (#1088): the credential-bearing
    ``/model/new`` registration is Provider-internal setup handed to the
    Invocation's ``setup`` hook, so a denied policy causes zero gateway calls
    instead of registering models before being told no. The billable/diagnostic
    completion crosses the canonical model egress so its outcome and usage are
    auditable, and the transient registration key never enters the Invocation
    record.
    """

    async def register_then_probe() -> None:
        try:
            await register_provider_models(runtime.endpoint, models=models, api_key=api_key)
        except ProviderRegistrationError as exc:
            raise ProviderActivationError(str(exc)) from exc

    health_binding = binding.model_copy(update={"provider_name": provider_name})
    try:
        return await complete(
            runtime=runtime,
            binding=health_binding,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key=f"provider.health:{provider_name}",
            request=ModelChatRequest(
                model=provider_name,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            ),
            setup=register_then_probe,
        )
    except ProviderActivationError:
        raise
    except (BindingResolutionError, InvocationDenied, InvocationApprovalRequired) as exc:
        raise ProviderAuthorizationError(
            f"provider health authorization failed for {provider_name}"
        ) from exc
    except Exception as exc:
        raise ProviderHealthError(f"provider health check failed for {provider_name}") from exc


@dataclass(frozen=True)
class OperationIdentity:
    """Correlation identity minted as real canonical Run/NodeRun/Attempt records.

    Control-plane model effects (evaluator judgments, provider health checks)
    are not imaginary Attempts on someone else's Run: this adapter mints a
    canonical one-node child Run for the operation, so every Invocation recorded
    beneath it references records that actually exist on the canonical spine
    (#1088). ``parent_run_id`` ties the operation to the Run that requested it.
    """

    run_id: str
    node_run_id: str
    attempt_id: str
    operation: str


async def mint_operation_identity(
    runtime: GovernedModelRuntime,
    *,
    operation: str,
    workspace_id: str,
    project_id: str,
    parent_run_id: str = "",
    provenance: dict[str, Any] | None = None,
) -> OperationIdentity:
    """Mint the canonical Run -> NodeRun -> Attempt identity for one operation.

    Fails closed when the canonical spine is unavailable or the requesting Run
    does not exist: an Invocation must correlate to records that exist, not to
    invented strings. The child Run terminalizes through
    :func:`settle_operation_identity` once the operation's outcome is known.
    """

    store = runtime.run_store
    if store is None:
        raise RuntimeError(
            "canonical run correlation is unavailable without the core Container run store"
        )
    parent_run_id = parent_run_id.strip()
    if parent_run_id and await store.get_run(parent_run_id) is None:
        raise LookupError(f"canonical Run {parent_run_id!r} does not exist")
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=operation,
        nodes=[Node(node_id=operation, node_type="control-plane", name=operation)],
    )
    run = await store.create_run(
        graph,
        parent_run_id=parent_run_id or None,
        initial_status=RunStatus.QUEUED,
        provenance={
            "admission_source": "control-plane-operation",
            "operation": operation,
            **(provenance or {}),
        },
    )
    run = await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id=operation)
    for step in transition_path(node_run.status, RunStatus.RUNNING):
        node_run = await store.transition_node_run(node_run.node_run_id, step)
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    return OperationIdentity(
        run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        operation=operation,
    )


async def settle_operation_identity(
    runtime: GovernedModelRuntime,
    identity: OperationIdentity,
    *,
    outcome: str,
    result: Any = None,
    error: str | None = None,
) -> None:
    """Terminalize the minted operation records with the operation's truth.

    ``outcome`` is ``completed`` (work succeeded), ``failed`` (the work ran and
    did not succeed), or ``cancelled`` (authorization refused before the work
    ran). Distinct terminal states are what make an authorization refusal
    distinguishable from an execution failure in the canonical record too.
    """

    store = runtime.run_store
    if store is None:  # pragma: no cover - mint refuses first
        raise RuntimeError("cannot settle an operation without the canonical run store")
    terminal = {
        "completed": (AttemptStatus.COMPLETED, RunStatus.COMPLETED),
        "failed": (AttemptStatus.FAILED, RunStatus.FAILED),
        "cancelled": (AttemptStatus.CANCELLED, RunStatus.CANCELLED),
    }
    if outcome not in terminal:
        raise ValueError(f"unknown operation outcome {outcome!r}")
    attempt_status, run_status = terminal[outcome]
    attempt = await store.transition_attempt(
        identity.attempt_id,
        attempt_status,
        result=result,
        error=error,
    )
    if outcome == "completed":
        attempt_result = AttemptResult.from_attempt(attempt)
        await store.transition_node_run(
            identity.node_run_id,
            RunStatus.COMPLETED,
            result=attempt_result.result,
            error=attempt_result.error,
            accepted_outcome=AcceptedNodeOutcome(
                node_run_id=identity.node_run_id,
                attempt_result=attempt_result,
            ),
        )
    else:
        await store.transition_node_run(
            identity.node_run_id,
            run_status,
            error=error,
        )
    await store.transition_run(identity.run_id, run_status, result=result, error=error)


__all__ = [
    "GovernedModelRuntime",
    "OperationIdentity",
    "ProviderActivationError",
    "ProviderAuthorizationError",
    "ProviderHealthError",
    "complete",
    "control_plane_binding",
    "ensure_binding",
    "mint_operation_identity",
    "register_and_health_check",
    "resolve_binding",
    "settle_operation_identity",
]
