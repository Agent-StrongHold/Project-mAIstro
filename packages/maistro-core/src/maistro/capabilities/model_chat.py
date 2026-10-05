"""One governed model egress: Binding -> Invocation -> approved Provider (#56).

This module owns no HTTP. It composes the canonical authorities from
:mod:`maistro.capabilities.effect_context` with the ADR-079 model registry and
cost-aware router, so router/fallback/model-selection policy is preserved
inside the governed boundary instead of being replaced by it:

- a Binding that pins ``provider_name`` selects exactly that model, and an
  unknown or unavailable pin refuses rather than falling back (fallback
  cannot widen authorization, ADR-081226-6b46);
- an unpinned request naming a model keeps the explicit alias (today's
  gateway behavior);
- an unpinned request with no alias is selected by ``CostAwareRouter``,
  including its budget-constrained fallback chain.

Token usage is read from the gateway response and cost is computed from
registry metadata, then attached to the persisted canonical Invocation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.credential_routing import CredentialBackedProvider
from maistro.capabilities.invocation import (
    Invocation,
    InvocationUsage,
    ProviderResolver,
)
from maistro.capabilities.provider_adapters import (
    AdapterGatewayProvider,
    default_adapter_catalog,
)
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_CHAT_CAPABILITY,
    GatewayEndpoint,
    LlmGatewayProvider,
    ModelChatRequest,
    execute_model_chat,
)
from maistro.capabilities.types import Unavailable
from maistro.observability.correlation import current_execution_context
from maistro.providers.errors import ModelNotFoundError, NoEligibleModelError
from maistro.providers.types import (
    ModelMetadata,
    RouterBudget,
    RoutingTask,
    compute_cost_cents,
)
from maistro.quota.usage_report import reported_usage

if TYPE_CHECKING:
    from maistro.capabilities.effect_context import CapabilityEffectContext
    from maistro.capabilities.provider_adapters import ProviderAdapterCatalog
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter


def _gateway_usage(
    provider: LlmGatewayProvider | AdapterGatewayProvider, body: Any
) -> InvocationUsage | None:
    """Extract usage/cost metadata from one canonical response body.

    An adapter's ``usage_from`` hook reports first — it knows where its
    provider puts the numbers — and the canonical OpenAI-shape parser is the
    fallback, so usage reaches the canonical Invocation either way.
    """

    if not isinstance(body, dict):
        return None
    reported: tuple[int, int] | None = None
    if isinstance(provider, AdapterGatewayProvider):
        reported = provider.adapter.usage_from(body)
    if reported is None:
        reported = reported_usage(body)
    if reported is None:
        return None
    input_units, output_units = reported
    metadata = provider.metadata
    cost_cents = (
        compute_cost_cents(metadata, input_units, output_units) if metadata is not None else None
    )
    model_version = str(body.get("model") or "")
    return InvocationUsage(
        input_units=input_units,
        output_units=output_units,
        cost_cents=cost_cents,
        model=provider.name,
        model_version=model_version,
        provider=metadata.provider if metadata is not None else "llm-gateway",
    )


def _adapter_health_refusal(
    adapters: ProviderAdapterCatalog | None,
    provider: ResolvedCapabilityProvider,
) -> str | None:
    """Why canonical selection refuses an adapter whose latest probe failed.

    Unpinned routing never reaches this refusal on the happy path: recorded
    health is synced into registry availability, so ``CostAwareRouter.select``
    skips an unhealthy adapter's models up front and falls through to the next
    healthy candidate or fallback (ADR-038) — one failed adapter cannot take
    unpinned traffic offline. The check remains as the fail-closed backstop
    for catalogs wired without a sync and for pinned/aliased selections,
    which never fall back by policy.
    """

    if (
        adapters is None
        or not isinstance(provider, AdapterGatewayProvider)
        or adapters.is_healthy(provider.spec.adapter_id)
    ):
        return None
    return (
        f"adapter {provider.spec.adapter_id!r} failed its latest health probe; "
        "canonical selection refuses until it recovers"
    )


def _undeclared_capability(
    provider: LlmGatewayProvider | AdapterGatewayProvider,
    request: ModelChatRequest,
) -> str | None:
    """Why ``request`` needs a capability the resolved provider does not declare.

    Adapter capabilities fail explicitly (M9-E1): a tools or structured-output
    request against an adapter that did not declare the feature refuses as a
    typed unavailable resolution before any HTTP, instead of degrading silently
    or escaping through some permissive default. Gateway models keep their
    existing behavior.
    """

    if not isinstance(provider, AdapterGatewayProvider):
        return None
    missing: list[str] = []
    if (request.tools or request.tool_choice) and not provider.capabilities.tools:
        missing.append("tools/tool_choice")
    if request.response_format is not None and not provider.capabilities.structured_output:
        missing.append("response_format (structured output)")
    if not missing:
        return None
    return (
        f"model {provider.name!r} on adapter {provider.spec.adapter_id!r} does not declare "
        f"{', '.join(missing)}; unsupported features fail explicitly"
    )


def resolve_model_chat_provider(
    registry: LLMProviderRegistry,
    router: LLMRouter,
    *,
    alias: str = "",
    task: RoutingTask | None = None,
    budget: RouterBudget | None = None,
    adapters: ProviderAdapterCatalog | None = None,
) -> ProviderResolver:
    """Build the slot-specific resolver preserving ADR-079 selection policy.

    ``alias`` is the model the request itself names (empty means "let the
    cost-aware router select"). A Binding pin outranks it and must already
    exist in the configured ProviderRegistry; gateway registration alone is
    not model metadata registration.

    ``adapters`` resolves registered provider-adapter models to adapter
    providers; every other selection resolves to the shipped gateway exactly
    as before the adapter SDK existed. Selection policy is untouched: adapter
    models sit in the same registry, so the cost-aware router picks them under
    the same cost/latency/fallback rules.
    """

    async def resolve(binding: Binding) -> ResolvedCapabilityProvider | Unavailable:
        selection = binding.provider_name or alias
        if selection:
            return await _resolve_named_model(registry, adapters, binding, selection)
        try:
            selected = await router.select(
                task if task is not None else RoutingTask(task_type=MODEL_CHAT_CAPABILITY),
                budget,
            )
        except NoEligibleModelError as exc:
            return Unavailable(slot=MODEL_CHAT_CAPABILITY, reason=f"no eligible model: {exc}")
        routed = (
            adapters.resolve_provider(selected.name, selected) if adapters is not None else None
        )
        if routed is not None:
            # Backstop only: with the availability sync wired (bootstrap),
            # selection already skipped unhealthy adapter models, so the
            # router's fallback chain continued past them.
            refusal = _adapter_health_refusal(adapters, routed)
            if refusal is not None:
                return Unavailable(slot=MODEL_CHAT_CAPABILITY, reason=refusal)
            return routed
        return LlmGatewayProvider(selected, model=selected.name)

    return resolve


async def _resolve_named_model(
    registry: LLMProviderRegistry,
    adapters: ProviderAdapterCatalog | None,
    binding: Binding,
    selection: str,
) -> ResolvedCapabilityProvider | Unavailable:
    """Resolve an explicitly named (pinned or aliased) model selection."""

    try:
        metadata: ModelMetadata | None = await registry.get_model(selection)
    except ModelNotFoundError:
        if binding.provider_name:
            return Unavailable(
                slot=MODEL_CHAT_CAPABILITY,
                reason=(
                    f"pinned model {selection!r} is unknown; register its metadata "
                    "in the configured ProviderRegistry before using a Binding pin "
                    "(provider_config_path); gateway /model/new is not sufficient"
                ),
            )
        metadata = None
    if metadata is not None and not registry.is_available(metadata.name):
        source = "pinned model" if binding.provider_name else "request alias"
        return Unavailable(
            slot=MODEL_CHAT_CAPABILITY,
            reason=(
                f"{source} {selection!r} is unavailable; an explicit selection does not fall back"
            ),
        )
    resolved = adapters.resolve_provider(selection, metadata) if adapters is not None else None
    if resolved is not None:
        refusal = _adapter_health_refusal(adapters, resolved)
        if refusal is not None:
            return Unavailable(slot=MODEL_CHAT_CAPABILITY, reason=refusal)
        return resolved
    return LlmGatewayProvider(metadata, model=selection)


class GovernedLLMClient:
    """LLMClient adapter that sends every completion through ModelChatEgress.

    Agent strategies keep their existing LLMClient shape, while the actual
    provider call has one canonical Binding/Invocation authority. ``set_turn``
    is a small runtime context seam used by Agent.handle; it does not dispatch
    or own a second ledger.

    Turn identity is the canonical execution identity (#1827): ``set_turn``
    reads the Run/NodeRun/Attempt triple that canonical execution already bound
    on the correlation context — ``RunExecutionService`` binds ``run_id``;
    ``AttemptExecutionService.execute_claimed`` binds ``node_run_id`` and
    ``attempt_id`` — and never fabricates an agent-turn/agent-node/agent-attempt
    id to make an unadmitted call look governed. These values provide
    correlation, not authorization: Binding/credential/policy checks remain at
    the governed effect boundary inside :class:`ModelChatEgress`.
    """

    def __init__(
        self,
        effects: CapabilityEffectContext,
        *,
        registry: LLMProviderRegistry,
        router: LLMRouter,
        endpoint: GatewayEndpoint,
        workspace_id: str,
        project_id: str = "agent-runtime",
    ) -> None:
        self._egress = ModelChatEgress(effects, registry=registry, router=router, endpoint=endpoint)
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._turn: ContextVar[tuple[str, str, str] | None] = ContextVar(
            "governed_llm_turn", default=None
        )
        self._sequence: ContextVar[int] = ContextVar("governed_llm_sequence", default=0)

    def set_turn(self, run_id: str | None = None, *, agent_name: str = "") -> None:
        """Bind correlation identity for the next turn from canonical execution.

        Stores exactly the (run_id, node_run_id, attempt_id) triple the
        canonical execution services bound on the correlation context. When
        any of the three is missing or blank, raises
        :class:`maistro.runs.store.RunIntegrityError` instead of minting a
        synthetic identity. A supplied ``run_id`` must equal the bound one —
        it is checked, never substituted. ``agent_name`` is accepted for
        compatibility with the ``Agent`` turn seam and cannot manufacture a
        node id.

        Failure-atomic: any previously stored turn is dropped *before*
        validation, so a rejected ``set_turn`` cannot leave an earlier valid
        tuple usable behind it. On success the per-turn call sequence resets
        to zero, as before.
        """
        # Imported here, not at module level: `maistro.runs` transitively
        # imports `maistro.graph.nodes`, which imports this module, so an
        # eager import would make every `maistro.capabilities.model_chat`
        # import a cycle.
        from maistro.runs.store import RunIntegrityError

        del agent_name  # compatibility only; it cannot manufacture identity
        self._turn.set(None)
        self._sequence.set(0)
        context = current_execution_context()
        bound = (context.run_id, context.node_run_id, context.attempt_id)
        missing = [
            name
            for name, value in zip(("run_id", "node_run_id", "attempt_id"), bound, strict=True)
            if not value.strip()
        ]
        if missing:
            raise RunIntegrityError(
                "GovernedLLMClient requires the canonical execution context "
                "(run_id, node_run_id, attempt_id) bound by canonical execution; "
                f"missing or blank: {', '.join(missing)}"
            )
        if run_id and run_id != bound[0]:
            raise RunIntegrityError(
                f"explicit run_id {run_id!r} does not match the bound execution "
                f"run_id {bound[0]!r}; the bound identity is never replaced"
            )
        self._turn.set(bound)

    def clear_turn(self) -> None:
        self._turn.set(None)
        self._sequence.set(0)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del stream, metadata
        from maistro.runs.store import RunIntegrityError

        if self._turn.get() is None:
            # No explicit turn: adopt the currently bound canonical context.
            # An incomplete context raises RunIntegrityError right here, with
            # zero egress calls.
            self.set_turn()
        context = current_execution_context()
        live = (context.run_id, context.node_run_id, context.attempt_id)
        turn = self._turn.get()
        assert turn is not None
        if live != turn:
            # The context has ended or moved to another Attempt: the stored
            # triple is stale. Drop it and refuse instead of attributing the
            # call to a dead identity; an explicit set_turn starts the next
            # turn.
            self.clear_turn()
            raise RunIntegrityError(
                f"current execution context {live} does not match the stored "
                f"turn {turn}; call set_turn to start the new turn explicitly"
            )
        self._sequence.set(self._sequence.get() + 1)
        run_id, node_run_id, attempt_id = turn
        request = ModelChatRequest(
            model=model,
            messages=[dict(message) for message in messages],
            temperature=0.7 if temperature is None else temperature,
            max_tokens=max_tokens,
            tools=[dict(tool) for tool in tools] if tools else None,
            tool_choice=tool_choice,
        )
        result = await self._egress.complete(
            binding=Binding(
                workspace_id=self._workspace_id,
                project_id=self._project_id,
                capability=MODEL_CHAT_CAPABILITY,
                # Bind-scoped credential routing (#1091) refuses a Binding
                # that names no credential: authorize the deployment's
                # registered default gateway key. Acquire still fails closed
                # unless that ref exists in exactly this Workspace/Project
                # scope, so naming it widens nothing.
                credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
            ),
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key=f"agent-llm-{self._sequence.get()}",
            request=request,
        )
        return result.body

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Compatibility stream; canonical egress remains one non-stream call."""
        body = await self.complete(messages, model, **kwargs)
        yield body


class ModelCallResult(BaseModel):
    """Governed model-call outcome plus the Invocation that records it."""

    model_config = ConfigDict(extra="forbid")

    invocation_id: str
    model: str
    body: dict[str, Any]
    usage: InvocationUsage | None = None


class ModelChatEgress:
    """Cross the one governed model boundary on behalf of an effect consumer.

    ``adapters`` selects registered provider-adapter models (M9-E1); ``None``
    means the process default, and an unconfigured default leaves the egress
    gateway-only — an adapter can add a destination, never a second boundary.
    """

    def __init__(
        self,
        effects: CapabilityEffectContext,
        *,
        registry: LLMProviderRegistry,
        router: LLMRouter,
        endpoint: GatewayEndpoint,
        adapters: ProviderAdapterCatalog | None = None,
    ) -> None:
        self._effects = effects
        self._registry = registry
        self._router = router
        self._endpoint = endpoint
        self._adapters = adapters if adapters is not None else default_adapter_catalog()

    async def complete(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        request: ModelChatRequest,
        setup: Callable[[], Awaitable[None]] | None = None,
        actor_id: str = "",
    ) -> ModelCallResult:
        """Run one governed model call, optionally performing provider setup.

        ``setup`` runs inside the Invocation executor — after Binding scope
        resolution and policy authorization, immediately before the physical
        completion (#1088). Provider-internal mechanics that carry credentials
        (e.g. a gateway's model registration) must be passed here rather than
        performed by the caller beforehand: a denied policy then causes zero
        HTTP, not a credential-bearing side request ahead of authorization.
        """
        resolver = resolve_model_chat_provider(
            self._registry,
            self._router,
            alias=request.model,
            adapters=self._adapters,
        )
        selected: list[LlmGatewayProvider | AdapterGatewayProvider] = []

        async def tracked_resolve(candidate: Binding) -> ResolvedCapabilityProvider | Unavailable:
            provider = await resolver(candidate)
            if isinstance(provider, (LlmGatewayProvider, AdapterGatewayProvider)):
                refusal = _undeclared_capability(provider, request)
                if refusal is not None:
                    return Unavailable(slot=MODEL_CHAT_CAPABILITY, reason=refusal)
                selected[:] = [provider]
            return provider

        async def execute(provider: ResolvedCapabilityProvider, payload: Any) -> Any:
            if not isinstance(provider, CredentialBackedProvider):
                raise TypeError(
                    "model-chat physical execution requires a Binding-scoped credential"
                )
            base = provider.base
            if not isinstance(base, (LlmGatewayProvider, AdapterGatewayProvider)):
                raise TypeError(f"credential routed a non-gateway provider: {base!r}")
            if setup is not None:
                await setup()
            endpoint = self._endpoint.model_copy(update={"api_key": provider.credential.api_key})
            return await execute_model_chat(base, payload, endpoint=endpoint)

        routing = self._effects.credential_routing()
        routed_resolver = routing.resolver(tracked_resolve)
        routed_executor = routing.executor(execute)

        def usage_from(body: Any) -> InvocationUsage | None:
            if not selected:
                return None
            return _gateway_usage(selected[0], body)

        invocation: Invocation = await self._effects.invocations.invoke(
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key=effect_key,
            request=request,
            resolver=routed_resolver,
            executor=routed_executor,
            usage_from=usage_from,
            actor_id=actor_id,
        )
        body = invocation.result if isinstance(invocation.result, dict) else {}
        return ModelCallResult(
            invocation_id=invocation.invocation_id,
            model=invocation.binding.provider_name,
            body=dict(body),
            usage=invocation.usage,
        )


__all__ = [
    "MODEL_CHAT_CAPABILITY",
    "GovernedLLMClient",
    "ModelCallResult",
    "ModelChatEgress",
    "ModelChatRequest",
    "resolve_model_chat_provider",
]
