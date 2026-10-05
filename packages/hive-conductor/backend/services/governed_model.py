"""Hive composition for the canonical model Capability/Provider effect path.

This module is an application adapter, not a second model gateway. It obtains
maistro-core's container-owned Binding and Invocation authorities and exposes
small operations for shipped control-plane consumers. Secrets are accepted only
for the provider's transient registration call; health-check requests and
Invocation records contain no credential material. Authorization precedes every
HTTP effect: provider registration is Invocation-internal setup (#1088), and
evaluator/health invocations correlate to canonical Run/NodeRun/Attempt records
admitted by the requesting domain, never to invented identifiers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from maistro.agents.types import LLMProviderError
from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import BindingResolutionError, register_boot_binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.governed_invocation import (
    InvocationApprovalRequired,
    InvocationDenied,
)
from maistro.capabilities.invocation import CapabilityUnavailable
from maistro.capabilities.model_chat import ModelCallResult, ModelChatEgress, ModelSetupError
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_CHAT_CAPABILITY,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    GatewayEndpoint,
    ModelChatRequest,
    register_provider_models,
)
from maistro.credentials.router import CredentialScopeError
from maistro.credentials.types import CredentialRecord
from maistro.graph.nodes.base import NodeContext
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
    runtime: GovernedModelRuntime,
    *,
    binding_id: str,
    workspace_id: str,
    project_id: str,
    provider_name: str = "",
) -> Binding:
    """Build the explicit operator-scoped Binding used by control-plane effects.

    Registers the runtime's own gateway credential in this Binding's scope
    (idempotent -- ``CredentialRouter.add`` refreshes the same ``key_id`` in
    place rather than duplicating it, and -- since #1079 Finding 2 -- without
    discarding any ``blocked``/``cooldown_until``/error-counter health state a
    prior 401/403/429 already set for it; consecutive control-plane calls
    reusing the same Workspace/Project must not reset a backoff decision this
    call didn't make) and authorizes it by ref, mirroring
    ``bootstrap_model_bindings`` (#1248, #1091, Binding-scoped credential
    routing): the physical model call refuses with ``CredentialScopeError``
    before any HTTP unless the Binding names a credential actually registered
    in its own Workspace/Project scope, and a control-plane Binding built with
    no ``credential_refs`` at all would always refuse.
    """

    runtime.effects.credentials.add(
        workspace_id=workspace_id,
        project_id=project_id,
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key=runtime.endpoint.api_key,
        ),
    )
    return control_plane_binding_definition(
        binding_id=binding_id,
        workspace_id=workspace_id,
        project_id=project_id,
        provider_name=provider_name,
    )


def control_plane_binding_definition(
    *, binding_id: str, workspace_id: str, project_id: str, provider_name: str
) -> Binding:
    """Build the shipped immutable definition without changing credential state."""
    return Binding(
        binding_id=binding_id,
        workspace_id=workspace_id,
        project_id=project_id,
        node_id="control-plane",
        capability=MODEL_CHAT_CAPABILITY,
        provider_name=provider_name,
        credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
    )


def dag_node_runtime(container: Any) -> GovernedModelRuntime | None:
    """Retain the existing model-backed tool runtime composition.

    Ordinary model nodes use ``dag_node_model_calls``. This compatibility
    composition keeps the tool path's gateway selection unchanged until that
    caller's own migration; a missing runtime makes model-backed tools refuse.
    """

    if container is None:
        return None
    effects = getattr(container, "capability_effects", None)
    registry = getattr(container, "provider_registry", None)
    router = getattr(container, "llm_router", None)
    if effects is None or registry is None or router is None:
        return None
    try:
        endpoint = _endpoint()
    except ProviderActivationError:
        return None
    return GovernedModelRuntime(
        effects=effects,
        registry=registry,
        router=router,
        endpoint=endpoint,
    )


def dag_node_model_calls(container: Any) -> AdmittedModelCalls | None:
    """Compose ordinary model dispatch without granting credentials or Bindings.

    The selected Container owns execution, configuration and every authority.
    Absence makes real model calls fail closed. Explicit zero-effect dry runs
    have a separate no-configuration check; isolated and tool model paths
    retain their separate composition until their own migration.
    """
    if container is None:
        return None
    effects = getattr(container, "capability_effects", None)
    registry = getattr(container, "provider_registry", None)
    router = getattr(container, "llm_router", None)
    run_store = getattr(container, "run_store", None)
    config = getattr(container, "config", None)
    if any(value is None for value in (effects, registry, router, run_store, config)):
        return None
    base_url = str(config.litellm_url or "").strip()
    if not base_url:
        return None
    return AdmittedModelCalls(
        effects,
        registry=registry,
        router=router,
        endpoint=GatewayEndpoint(base_url=base_url),
        run_store=run_store,
        binding_ids=tuple(binding.binding_id for binding in config.model_bindings),
    )


def dag_node_unconfigured(container: Any) -> bool:
    """Prove absence of real model configuration before permitting dry-run mode.

    Missing admission collaborators alone do not prove a no-gateway deployment.
    A configured endpoint or any declared model grant keeps the real path
    fail-closed. Settings owns gateway aliases; do not re-resolve them here.
    """
    config = getattr(container, "config", None)
    if config is not None and (config.litellm_url or config.model_bindings):
        return False
    from config import get_settings

    try:
        settings = get_settings()
        return not (settings.litellm_api_base or settings.maistro_model_bindings)
    except Exception:
        # Unavailable configuration is not evidence of deliberate dry-run mode.
        return False


async def dag_node_completion(
    calls: AdmittedModelCalls,
    *,
    ctx: NodeContext,
    binding_id: str = "",
    system: str,
    user: str,
    model: str,
    timeout_s: float,
) -> str:
    """Use admitted execution and configured authority for one ordinary node.

    The model is request data, never a self-issued Binding pin. Persisted
    execution owns actor/scope/lease validation, and canonical terminalization
    records usage once. The logical effect survives a later Attempt so replay
    and UNKNOWN protection cannot be bypassed by retrying the node.
    """
    result = await calls.complete(
        identity=(ctx.run_id, ctx.node_run_id, ctx.attempt_id),
        binding_id=binding_id,
        effect_key="dag:model",
        timeout_s=timeout_s,
        request=ModelChatRequest(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        ),
    )
    choices = result.body.get("choices")
    message = (
        choices[0].get("message")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict)
        else None
    )
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LLMProviderError("dag node: governed gateway returned no content")
    return content


async def dag_tool_completion(
    runtime: GovernedModelRuntime,
    *,
    ctx: NodeContext,
    binding_id: str,
    effect_key: str,
    request: ModelChatRequest,
    timeout_s: float,
) -> str:
    """Execute a tool's model sub-effect using its existing canonical Attempt.

    The DAG only references an operator-declared model Binding. It cannot
    register a credential or authorize its requested model by constructing a
    new Binding. The outer tool Invocation retains tool policy/lifecycle;
    this distinct model Invocation owns model selection, credentials and usage.
    """
    if not binding_id.strip():
        raise BindingResolutionError("model-backed DAG tools require a model_binding_id")
    binding = await runtime.effects.bindings.resolve(
        binding_id,
        workspace_id=str(ctx.workspace_id or ""),
        project_id=str(ctx.project_id or ""),
        node_id=ctx.node_id,
        capability=MODEL_CHAT_CAPABILITY,
    )
    result = await ModelChatEgress(
        runtime.effects,
        registry=runtime.registry,
        router=runtime.router,
        endpoint=runtime.endpoint.model_copy(update={"timeout_s": timeout_s}),
    ).complete(
        binding=binding,
        run_id=ctx.run_id,
        node_run_id=ctx.node_run_id,
        attempt_id=ctx.attempt_id,
        actor_id=str(ctx.user_id or ""),
        effect_key=effect_key,
        request=request,
    )
    choices = result.body.get("choices")
    message = (
        choices[0].get("message")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict)
        else None
    )
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LLMProviderError("DAG tool model returned no text content")
    return content


async def ensure_binding(runtime: GovernedModelRuntime, binding: Binding) -> Binding:
    """Register an immutable control-plane Binding once, then reuse it."""

    try:
        return await register_boot_binding(runtime.effects.bindings, binding)
    except ValueError as exc:
        raise BindingResolutionError(
            f"Binding {binding.binding_id!r} is immutable and does not match the request"
        ) from exc


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
    record. The health model is a Binding pin: its metadata must already be
    registered by the configured ProviderRegistry (``provider_config_path``).
    This hook registers gateway transport names, not trusted cost metadata.
    An unknown pin refuses before setup and must remain an actionable error.
    """

    if runtime.run_store is None:
        raise RuntimeError("canonical provider activation requires the Container run store")
    calls = AdmittedModelCalls(
        runtime.effects,
        registry=runtime.registry,
        router=runtime.router,
        endpoint=runtime.endpoint,
        run_store=runtime.run_store,
        binding_ids=(binding.binding_id,),
    )

    async def register_then_probe() -> None:
        await register_provider_models(runtime.endpoint, models=models, api_key=api_key)

    identity = (run_id, node_run_id, attempt_id)
    try:
        pin = await calls.pinned_model(identity=identity, binding_id=binding.binding_id)
        if pin != provider_name:
            raise BindingResolutionError("provider health Binding pin does not match the catalogue")
        return await calls.complete(
            identity=identity,
            binding_id=binding.binding_id,
            effect_key=f"provider.health:{provider_name}",
            request=ModelChatRequest(
                model=provider_name,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            ),
            setup=register_then_probe,
        )
    except ModelSetupError:
        raise ProviderActivationError("model gateway provider registration failed") from None
    except CapabilityUnavailable:
        raise ProviderHealthError(
            "provider health pinned model or scoped credential is unavailable; "
            "an explicit selection does not fall back. Register metadata in the "
            "configured ProviderRegistry (provider_config_path); gateway /model/new "
            "is not sufficient"
        ) from None
    except (
        BindingResolutionError,
        InvocationDenied,
        InvocationApprovalRequired,
        CredentialScopeError,
    ):
        raise ProviderAuthorizationError(
            f"provider health authorization failed for {provider_name}"
        ) from None
    except Exception:
        raise ProviderHealthError(f"provider health check failed for {provider_name}") from None


__all__ = [
    "GovernedModelRuntime",
    "ProviderActivationError",
    "ProviderAuthorizationError",
    "ProviderHealthError",
    "control_plane_binding",
    "ensure_binding",
    "register_and_health_check",
    "resolve_binding",
]
