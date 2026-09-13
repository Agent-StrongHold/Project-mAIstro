"""One governed model egress: Binding -> Invocation -> approved Provider (#56).

This module owns no HTTP. It composes the canonical authorities from
:mod:`maistro.capabilities.effect_context` with the ADR-079 model registry and
cost-aware router, so router/fallback/model-selection policy is preserved
inside the governed boundary instead of being replaced by it:

- a Binding that pins ``provider_name`` selects exactly that model, and an
  unavailable pin refuses rather than falling back (fallback cannot widen
  authorization, ADR-081226-6b46);
- an unpinned request naming a model keeps the explicit alias (today's
  gateway behavior);
- an unpinned request with no alias is selected by ``CostAwareRouter``,
  including its budget-constrained fallback chain.

Token usage is read from the gateway response and cost is computed from
registry metadata, then attached to the persisted canonical Invocation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.invocation import (
    Invocation,
    InvocationUsage,
    ProviderResolver,
)
from maistro.capabilities.providers.llm_gateway import (
    MODEL_CHAT_CAPABILITY,
    GatewayEndpoint,
    LlmGatewayProvider,
    ModelChatRequest,
    execute_model_chat,
)
from maistro.capabilities.types import Unavailable
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
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter


def _gateway_usage(provider: LlmGatewayProvider, body: Any) -> InvocationUsage | None:
    """Extract usage/cost metadata from one gateway response body."""

    if not isinstance(body, dict):
        return None
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


def resolve_model_chat_provider(
    registry: LLMProviderRegistry,
    router: LLMRouter,
    *,
    alias: str = "",
    task: RoutingTask | None = None,
    budget: RouterBudget | None = None,
) -> ProviderResolver:
    """Build the slot-specific resolver preserving ADR-079 selection policy.

    ``alias`` is the model the request itself names (empty means "let the
    cost-aware router select"). A Binding pin outranks it.
    """

    async def resolve(binding: Binding) -> ResolvedCapabilityProvider | Unavailable:
        selection = binding.provider_name or alias
        if selection:
            try:
                metadata: ModelMetadata | None = await registry.get_model(selection)
            except ModelNotFoundError:
                metadata = None
            if metadata is not None and not registry.is_available(metadata.name):
                return Unavailable(
                    slot=MODEL_CHAT_CAPABILITY,
                    reason=(
                        f"selected model {selection!r} is unavailable and a pinned "
                        "selection does not fall back"
                    ),
                )
            return LlmGatewayProvider(metadata, model=selection)
        try:
            selected = await router.select(
                task if task is not None else RoutingTask(task_type=MODEL_CHAT_CAPABILITY),
                budget,
            )
        except NoEligibleModelError as exc:
            return Unavailable(slot=MODEL_CHAT_CAPABILITY, reason=f"no eligible model: {exc}")
        return LlmGatewayProvider(selected, model=selected.name)

    return resolve


class GovernedLLMClient:
    """LLMClient adapter that sends every completion through ModelChatEgress.

    Agent strategies keep their existing LLMClient shape, while the actual
    provider call has one canonical Binding/Invocation authority. ``set_turn``
    is a small runtime context seam used by Agent.handle; it does not dispatch
    or own a second ledger.
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
        """Set correlation identity for the next Agent turn."""
        self._turn.set(
            (
                run_id or f"agent-turn-{uuid4().hex}",
                f"agent-node-{agent_name or 'model'}",
                f"agent-attempt-{uuid4().hex}",
            )
        )
        self._sequence.set(0)

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
        del tool_choice, stream, metadata
        if self._turn.get() is None:
            self.set_turn()
        self._sequence.set(self._sequence.get() + 1)
        turn = self._turn.get()
        assert turn is not None
        run_id, node_run_id, attempt_id = turn
        request = ModelChatRequest(
            model=model,
            messages=[dict(message) for message in messages],
            temperature=0.7 if temperature is None else temperature,
            max_tokens=max_tokens,
            tools=[dict(tool) for tool in tools] if tools else None,
        )
        result = await self._egress.complete(
            binding=Binding(
                workspace_id=self._workspace_id,
                project_id=self._project_id,
                capability=MODEL_CHAT_CAPABILITY,
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
    """Cross the one governed model boundary on behalf of an effect consumer."""

    def __init__(
        self,
        effects: CapabilityEffectContext,
        *,
        registry: LLMProviderRegistry,
        router: LLMRouter,
        endpoint: GatewayEndpoint,
    ) -> None:
        self._effects = effects
        self._registry = registry
        self._router = router
        self._endpoint = endpoint

    async def complete(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        request: ModelChatRequest,
    ) -> ModelCallResult:
        resolver = resolve_model_chat_provider(self._registry, self._router, alias=request.model)
        selected: list[LlmGatewayProvider] = []

        async def tracked_resolve(candidate: Binding) -> ResolvedCapabilityProvider | Unavailable:
            provider = await resolver(candidate)
            if isinstance(provider, LlmGatewayProvider):
                selected[:] = [provider]
            return provider

        async def execute(provider: ResolvedCapabilityProvider, payload: Any) -> Any:
            return await execute_model_chat(provider, payload, endpoint=self._endpoint)

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
            resolver=tracked_resolve,
            executor=execute,
            usage_from=usage_from,
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
