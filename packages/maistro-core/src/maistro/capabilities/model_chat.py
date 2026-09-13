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

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager, suppress
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

if TYPE_CHECKING:
    from maistro.capabilities.effect_context import CapabilityEffectContext
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter


_DEFAULT_PROJECT_ID = "default"
_MODEL_EXECUTION_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar(
    "model_execution_context", default=None
)


@contextmanager
def model_execution_context(**values: str) -> Iterator[None]:
    """Expose the active canonical Run scope to compatibility LLM clients."""

    token = _MODEL_EXECUTION_CONTEXT.set(
        {key: value for key, value in values.items() if isinstance(value, str) and value}
    )
    try:
        yield
    finally:
        _MODEL_EXECUTION_CONTEXT.reset(token)


def _gateway_usage(provider: LlmGatewayProvider, body: Any) -> InvocationUsage | None:
    """Extract usage/cost metadata from one gateway response body."""

    if not isinstance(body, dict):
        return None
    usage = body.get("usage")
    usage_map = usage if isinstance(usage, dict) else {}
    input_units = int(usage_map.get("prompt_tokens") or 0)
    output_units = int(usage_map.get("completion_tokens") or 0)
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
    allow_unregistered_alias: bool = False,
) -> ProviderResolver:
    """Build the slot-specific resolver preserving ADR-079 selection policy.

    ``alias`` is the model the request itself names (empty means "let the
    cost-aware router select"). A Binding pin outranks it.
    """

    async def resolve(binding: Binding) -> ResolvedCapabilityProvider | Unavailable:
        selection = binding.provider_name or alias
        if selection:
            try:
                metadata: ModelMetadata = await registry.get_model(selection)
            except ModelNotFoundError:
                if allow_unregistered_alias:
                    return LlmGatewayProvider(None, model=selection)
                return Unavailable(
                    slot=MODEL_CHAT_CAPABILITY,
                    reason=f"selected model {selection!r} is not registered",
                )
            if not registry.is_available(metadata.name):
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
        setup: Callable[[], Awaitable[None]] | None = None,
        allow_unregistered_alias: bool = False,
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
            allow_unregistered_alias=allow_unregistered_alias,
        )
        selected: list[LlmGatewayProvider] = []

        async def tracked_resolve(candidate: Binding) -> ResolvedCapabilityProvider | Unavailable:
            provider = await resolver(candidate)
            if isinstance(provider, LlmGatewayProvider):
                selected[:] = [provider]
            return provider

        async def execute(provider: ResolvedCapabilityProvider, payload: Any) -> Any:
            if setup is not None:
                await setup()
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


class GovernedModelChatClient:
    """Compatibility LLM client backed exclusively by :class:`ModelChatEgress`.

    Domain adapters can keep their existing LLM interfaces while this client
    supplies the execution correlation and active Binding required by the
    canonical boundary. It intentionally exposes no transport or provider
    objects to callers.
    """

    def __init__(
        self,
        egress: ModelChatEgress,
        binding: Binding,
        *,
        protocol: str = "chat_completions",
    ) -> None:
        self._egress = egress
        self._binding = binding
        self._protocol = protocol

    async def _call(
        self,
        messages: list[dict[str, Any]],
        model: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        stream: bool = False,
        tool_choice: str | None = None,
    ) -> ModelCallResult:
        from maistro.observability.correlation import current_execution_context

        metadata = {
            **current_execution_context().as_log_fields(),
            **(_MODEL_EXECUTION_CONTEXT.get() or {}),
            **(metadata or {}),
        }
        request = ModelChatRequest(
            model=model,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature if temperature is not None else 0.7,
            response_format=response_format,
            protocol=("chat_completions" if tools else self._protocol),
            stream=stream,
            tool_choice=tool_choice,
        )
        workspace_id = str(metadata.get("workspace_id") or self._binding.workspace_id)
        project_id = str(metadata.get("project_id") or self._binding.project_id)
        binding = self._binding
        if workspace_id != binding.workspace_id or project_id != binding.project_id:
            binding = binding.model_copy(
                update={
                    "binding_id": f"model-chat:{workspace_id}:{project_id}",
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                }
            )
        # Registration is idempotent and keeps compatibility callers on the
        # same active Binding authority as graph/effect consumers.
        await self._egress._effects.bindings.put(binding)
        correlation = str(metadata.get("correlation_id") or uuid4().hex)
        return await self._egress.complete(
            binding=binding,
            run_id=str(metadata.get("run_id") or correlation),
            node_run_id=str(metadata.get("node_run_id") or f"llm:{correlation}"),
            attempt_id=str(metadata.get("attempt_id") or f"attempt:{correlation}"),
            effect_key=str(metadata.get("effect_key") or f"llm:{correlation}"),
            request=request,
            allow_unregistered_alias=True,
        )

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
        response_format: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self._call(
            messages,
            model,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            metadata=metadata,
            stream=stream,
            tool_choice=tool_choice,
        )
        return result.body

    async def stream_chunks(
        self,
        messages: list[dict[str, Any]],
        model: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        tool_choice: str | None = None,
    ) -> Any:
        result = await self._call(
            messages,
            model,
            tools=tools,
            metadata=metadata,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            tool_choice=tool_choice,
            stream=True,
        )
        chunks = result.body.get("_stream_chunks")
        if isinstance(chunks, list):
            for chunk in chunks:
                if isinstance(chunk, dict):
                    yield chunk
            return
        content = ""
        with suppress(KeyError, IndexError, TypeError):
            content = str(result.body["choices"][0]["message"].get("content") or "")
        yield {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]}

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> Any:
        async for chunk in self.stream_chunks(messages, model, **kwargs):
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            if isinstance(delta, dict) and delta.get("content"):
                yield str(delta["content"])


def build_model_chat_client(
    *,
    endpoint: GatewayEndpoint,
    workspace_id: str = "default",
    project_id: str = _DEFAULT_PROJECT_ID,
    effects: CapabilityEffectContext | None = None,
    registry: LLMProviderRegistry | None = None,
    router: LLMRouter | None = None,
    protocol: str = "chat_completions",
    binding: Binding | None = None,
) -> GovernedModelChatClient:
    """Compose the canonical compatibility client for an app boundary."""

    if effects is None:
        from maistro.capabilities.effect_context import default_effect_context

        effects = default_effect_context()
    if registry is None:
        from maistro.providers.registry import InMemoryProviderRegistry

        registry = InMemoryProviderRegistry()
    if router is None:
        from maistro.providers.router import CostAwareRouter

        router = CostAwareRouter(registry)
    active_binding = binding or Binding(
        workspace_id=workspace_id,
        project_id=project_id,
        capability=MODEL_CHAT_CAPABILITY,
    )
    egress = ModelChatEgress(effects, registry=registry, router=router, endpoint=endpoint)
    return GovernedModelChatClient(egress, active_binding, protocol=protocol)


__all__ = [
    "MODEL_CHAT_CAPABILITY",
    "GovernedModelChatClient",
    "ModelCallResult",
    "ModelChatEgress",
    "build_model_chat_client",
    "model_execution_context",
    "resolve_model_chat_provider",
]
