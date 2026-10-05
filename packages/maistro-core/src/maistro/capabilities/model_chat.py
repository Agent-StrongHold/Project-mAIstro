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

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.credential_routing import CredentialBackedProvider
from maistro.capabilities.invocation import (
    Invocation,
    InvocationUsage,
    ProviderExecutor,
    ProviderResolver,
)
from maistro.capabilities.model_chat_stream import StreamDelivery, stream_model_call
from maistro.capabilities.providers.llm_gateway import (
    MODEL_CHAT_CAPABILITY,
    GatewayEndpoint,
    LlmAuthError,
    LlmGatewayProvider,
    LlmHttpError,
    ModelChatRequest,
    execute_model_chat,
    execute_model_chat_stream,
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
    from maistro.capabilities.admitted_model import AdmittedModelCalls
    from maistro.capabilities.effect_context import CapabilityEffectContext
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter


class ModelSetupError(RuntimeError):
    """Provider-internal preparation failed with an unknown external outcome."""


async def _prepare_model_setup(setup: Callable[[], Awaitable[None]]) -> None:
    """Sanitize admin setup before Invocation, outside scoped probe health."""
    failed = False
    try:
        await setup()
    except Exception:
        failed = True
    # Raise outside the handler: the credential classifier traverses exception
    # context even when ``from None`` suppresses traceback presentation.
    if failed:
        raise ModelSetupError("model gateway provider registration failed")


def _with_model_setup(
    executor: ProviderExecutor, setup: Callable[[], Awaitable[None]] | None
) -> ProviderExecutor:
    async def execute(provider: ResolvedCapabilityProvider, payload: Any) -> Any:
        if setup is not None:
            await _prepare_model_setup(setup)
        return await executor(provider, payload)

    return execute


async def _complete_after_setup(
    provider: LlmGatewayProvider, payload: Any, *, endpoint: GatewayEndpoint
) -> Any:
    """A probe cannot prove that earlier registration had no external effect.

    Preserve only bounded status metadata for scoped credential health. Raw
    transport text and contexts must reach neither that classifier nor the
    canonical Invocation ledger. Connection failures remain UNKNOWN here.
    """
    failure: Exception
    try:
        return await execute_model_chat(provider, payload, endpoint=endpoint)
    except (LlmAuthError, LlmHttpError) as exc:
        raw_status = exc.status_code
        status = raw_status if type(raw_status) is int and 100 <= raw_status <= 599 else 0
        failure = LlmHttpError(f"model gateway probe failed: HTTP {status}", status_code=status)
    except Exception:
        failure = RuntimeError("model gateway probe failed after provider registration")
    raise failure


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
    cost-aware router select"). A Binding pin outranks it and must already
    exist in the configured ProviderRegistry; gateway registration alone is
    not model metadata registration.
    """

    async def resolve(binding: Binding) -> ResolvedCapabilityProvider | Unavailable:
        selection = binding.provider_name or alias
        if selection:
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
                        f"{source} {selection!r} is unavailable; "
                        "an explicit selection does not fall back"
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
    provider call uses the configured AdmittedModelCalls to join persisted
    execution, actor and operator Binding authority. No scope or Binding is
    synthesized by this client. ``set_turn``
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

    def __init__(self, admitted_calls: AdmittedModelCalls) -> None:
        self._calls = admitted_calls
        self._turn: ContextVar[tuple[str, str, str] | None] = ContextVar(
            "governed_llm_turn", default=None
        )
        self._sequence: ContextVar[int] = ContextVar("governed_llm_sequence", default=0)
        self._effect_scope: ContextVar[tuple[str, int] | None] = ContextVar(
            "governed_llm_effect_scope", default=None
        )

    def set_turn(
        self,
        run_id: str | None = None,
        *,
        agent_name: str = "",
        delegation_depth: int = 0,
    ) -> None:
        """Bind correlation identity for the next turn from canonical execution.

        Stores exactly the (run_id, node_run_id, attempt_id) triple the
        canonical execution services bound on the correlation context. When
        any of the three is missing or blank, raises
        :class:`maistro.runs.store.RunIntegrityError` instead of minting a
        synthetic identity. A supplied ``run_id`` must equal the bound one —
        it is checked, never substituted. ``agent_name`` and the existing
        delegation depth distinguish logical model effects inside one Attempt;
        neither can manufacture or replace canonical execution identity.

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

        self._effect_scope.set(None)
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
        if agent_name:
            self._effect_scope.set((agent_name, delegation_depth))

    def set_agent_turn(self, *, agent_name: str, delegation_depth: int) -> None:
        """Opt into Agent tail-delegation effect scoping without new identity.

        Agent uses this optional hook so clients with the older ``set_turn``
        signature still receive only their existing ``agent_name`` argument.
        """
        self.set_turn(agent_name=agent_name, delegation_depth=delegation_depth)

    def clear_turn(self) -> None:
        self._effect_scope.set(None)
        self._turn.set(None)
        self._sequence.set(0)

    def _prepare_call(
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
    ) -> tuple[ModelChatRequest, tuple[str, str, str], str]:
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
        request = ModelChatRequest(
            model=model,
            messages=[dict(message) for message in messages],
            temperature=0.7 if temperature is None else temperature,
            max_tokens=max_tokens,
            tools=[dict(tool) for tool in tools] if tools else None,
            tool_choice=tool_choice,
        )
        scope = self._effect_scope.get()
        effect_key = (
            f"agent-llm:{scope[0]}:{scope[1]}:{self._sequence.get()}"
            if scope is not None
            else f"agent-llm-{self._sequence.get()}"
        )
        return request, turn, effect_key

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
        request, identity, effect_key = self._prepare_call(
            messages,
            model,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
            max_tokens=max_tokens,
            temperature=temperature,
            metadata=metadata,
        )
        result = await self._calls.complete(
            request=request, identity=identity, effect_key=effect_key
        )
        return result.body

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield admitted incremental chunks and close the canonical stream.

        Consumers that stop early must close this iterator (for example with
        ``contextlib.aclosing``) before leaving their execution context.
        """
        request, identity, effect_key = self._prepare_call(messages, model, **kwargs)
        async with aclosing(
            self._calls.stream(request=request, identity=identity, effect_key=effect_key)
        ) as chunks:
            async for chunk in chunks:
                yield chunk


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
        return await self._invoke(
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key=effect_key,
            request=request,
            setup=setup,
            actor_id=actor_id,
        )

    def stream(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        request: ModelChatRequest,
        actor_id: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Incremental raw chunks; one marked assembled chunk on effect replay.

        Callers that stop consumption early must close the returned iterator
        (for example with ``contextlib.aclosing``) so the canonical Invocation
        can record cancellation before its execution context goes away.
        """

        async def invoke(delivery: StreamDelivery) -> ModelCallResult:
            return await self._invoke(
                binding=binding,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                effect_key=effect_key,
                request=request,
                actor_id=actor_id,
                delivery=delivery,
            )

        return stream_model_call(invoke)

    async def _invoke(
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
        delivery: StreamDelivery | None = None,
    ) -> ModelCallResult:
        resolver = resolve_model_chat_provider(self._registry, self._router, alias=request.model)
        selected: list[LlmGatewayProvider] = []

        async def tracked_resolve(candidate: Binding) -> ResolvedCapabilityProvider | Unavailable:
            provider = await resolver(candidate)
            if isinstance(provider, LlmGatewayProvider):
                selected[:] = [provider]
            return provider

        async def execute(provider: ResolvedCapabilityProvider, payload: Any) -> Any:
            if not isinstance(provider, CredentialBackedProvider):
                raise TypeError(
                    "model-chat physical execution requires a Binding-scoped credential"
                )
            base = provider.base
            if not isinstance(base, LlmGatewayProvider):
                raise TypeError(f"credential routed a non-gateway provider: {base!r}")
            endpoint = self._endpoint.model_copy(update={"api_key": provider.credential.api_key})
            if setup is not None:
                return await _complete_after_setup(base, payload, endpoint=endpoint)
            if delivery is not None:
                delivery.start_provider()
                try:
                    return await execute_model_chat_stream(
                        base,
                        payload,
                        endpoint=endpoint,
                        on_chunk=delivery.publish,
                    )
                finally:
                    # Success, protocol/transport failure, or cancellation all
                    # leave physical dispatch here. Never cancel the canonical
                    # terminal write that the Invocation performs afterward.
                    delivery.provider_finished = True
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
            executor=_with_model_setup(routed_executor, setup),
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
