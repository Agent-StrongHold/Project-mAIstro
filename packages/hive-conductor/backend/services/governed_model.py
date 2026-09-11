"""Hive composition for the canonical model Capability/Provider effect path.

This module is an application adapter, not a second model gateway. It obtains
maistro-core's container-owned Binding and Invocation authorities and exposes
small operations for shipped control-plane consumers. Secrets are accepted only
for the provider's transient registration call; health-check requests and
Invocation records contain no credential material.
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
from maistro.providers.protocols import LLMProviderRegistry, LLMRouter


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
) -> ModelCallResult:
    """Execute a model request through canonical Binding -> Invocation."""

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
    """Register a provider then run its health check as a governed Invocation.

    LiteLLM's ``/model/new`` calls are Provider-internal registration mechanics.
    The billable/diagnostic completion is deliberately separate and crosses the
    canonical model egress so its outcome and usage are auditable.
    """

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
        )
    except (BindingResolutionError, InvocationDenied, InvocationApprovalRequired) as exc:
        raise ProviderAuthorizationError(
            f"provider health authorization failed for {provider_name}"
        ) from exc
    except Exception as exc:
        raise ProviderHealthError(f"provider health check failed for {provider_name}") from exc


__all__ = [
    "GovernedModelRuntime",
    "ProviderActivationError",
    "ProviderAuthorizationError",
    "ProviderHealthError",
    "complete",
    "control_plane_binding",
    "ensure_binding",
    "register_and_health_check",
    "resolve_binding",
]
