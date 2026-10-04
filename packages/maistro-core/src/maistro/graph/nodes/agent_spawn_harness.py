"""`agent.spawn_harness` — spawn an external agent harness as a governed DAG effect.

A harness adapter remains provider-specific: it knows how to dispatch to Claude
Code, another Conductor, an in-process harness, or a generic HTTP endpoint. It
does not own universal effect lifecycle or authorization. First dispatch now
resolves a canonical Workspace/Project-scoped Binding and crosses the governed
Invocation boundary before the physical adapter call. The node then pauses the
canonical Run until the harness result is supplied on resume.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.capabilities.slots.harness_runner import HarnessRunner
from maistro.capabilities.types import Unavailable
from maistro.graph.harness import (
    HarnessAdapter,
    HarnessHandle,
    HarnessRequest,
    HarnessResult,
    HarnessRunnerDispatchAdapter,
)

from . import register_node
from .base import (
    PAUSE_AWAITING_HARNESS,
    BaseNode,
    NodeContext,
    ReplaySemantics,
    pause_until,
    replay_effect_key,
)
from .capability_effect import invoke_capability_effect


class SpawnHarnessIn(BaseModel):
    harness_type: str = Field(
        description="Harness provider kind: claude_code, conductor, generic_http, in_process"
    )
    task: str = Field(description="Task description handed to the harness")
    context: dict[str, Any] = Field(
        default_factory=dict, description="Additional context for the harness"
    )
    timeout_seconds: int = Field(default=3600, description="Hard deadline in seconds")
    workdir: str = Field(
        default="",
        description=(
            "Workspace hint handed to the harness provider (repo/checkout the "
            "harness acts on); recorded on the Invocation. Empty = provider default."
        ),
    )
    binding_id: str = Field(
        default="",
        description=(
            "Reference to a pre-authorized canonical Binding. Naming an id does not grant "
            "authority; the Binding store resolves it against the executing scope."
        ),
    )


class SpawnHarnessOut(BaseModel):
    status: Literal["completed", "failed", "timed_out"] = "completed"
    handle_id: str = ""
    output: str = ""
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _detail_payload(handle: HarnessHandle) -> dict[str, Any]:
    """Adapter-vouched dispatch provenance for the Invocation result row."""
    detail = handle.detail
    return dict(detail) if isinstance(detail, dict) else {}


def _as_dispatch_adapter(provider: HarnessAdapter | HarnessRunner) -> HarnessAdapter:
    """Accept either a graph dispatch adapter or a session-protocol provider."""
    if isinstance(provider, HarnessAdapter):
        return provider
    if isinstance(provider, HarnessRunner):
        return HarnessRunnerDispatchAdapter(provider)
    raise TypeError(
        "harness adapter must be a HarnessAdapter or a HarnessRunner provider; "
        f"got {type(provider).__name__}"
    )


def _merge_poll_evidence(resumed: Any, result: HarnessResult) -> dict[str, Any]:
    """Overlay a successful poll's evidence onto the transported resume answer.

    The adapter vouches for the output; poll metadata extends (and on conflict
    overrides) what the resume answer recorded instead of discarding it.
    """
    merged = dict(resumed)
    if result.output:
        merged["output"] = result.output
    if isinstance(result.metadata, dict) and result.metadata:
        merged_metadata = dict(resumed.get("metadata") or {})
        merged_metadata.update(result.metadata)
        merged["metadata"] = merged_metadata
    return merged


@dataclass(frozen=True)
class _HarnessDispatchProvider:
    """Provider metadata plus the provider-specific adapter implementation."""

    name: str
    adapter: HarnessAdapter
    slot: str = "harness_runner"
    trust_tier: str = "configured"


@register_node
class AgentSpawnHarnessNode(BaseNode[SpawnHarnessIn, SpawnHarnessOut]):
    """Dispatch through Binding -> governed Invocation, then pause for the result."""

    kind: ClassVar[str] = "agent.spawn_harness"
    # Both degrade truthfully when absent: no adapters means every harness
    # request is refused as unknown, and the process-default effect context
    # registers no Bindings and therefore authorizes nothing.
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "adapters": "harness_adapters",
        "effect_context": "effect_context",
    }
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = SpawnHarnessIn
    output_schema: ClassVar[type[BaseModel]] = SpawnHarnessOut
    cost_hint: ClassVar[float] = 5.0
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Agent: spawn harness"
    description: ClassVar[str] = (
        "Dispatch a task to an authorized external agent-harness provider through "
        "canonical Binding/Invocation semantics and pause until it completes."
    )
    capability: ClassVar[str] = "harness_runner"

    def __init__(
        self,
        adapters: Mapping[str, HarnessAdapter | HarnessRunner] | None = None,
        *,
        effect_context: CapabilityEffectContext | None = None,
    ) -> None:
        # Adding a harness is a Provider + Binding, not a new product (#1613):
        # a provider speaking the SPEC-208 HarnessRunner session protocol is
        # wrapped in the one bridging adapter here, so callers can pass either
        # shape. Everything then crosses the same governed Invocation seam.
        self._adapters: dict[str, HarnessAdapter] = {
            name: _as_dispatch_adapter(adapter) for name, adapter in (adapters or {}).items()
        }
        self._effects = effect_context or default_effect_context()

    def replay_effect_key(self, inputs: SpawnHarnessIn, ctx: NodeContext) -> str:
        return replay_effect_key(
            ctx,
            "agent.spawn_harness.dispatch",
            inputs.model_dump(mode="json"),
        )

    @staticmethod
    def _resume_output(resumed: Any) -> SpawnHarnessOut:
        """Rebuild the node output from a paused run's recorded resume answer."""
        return SpawnHarnessOut(
            status=resumed.get("status", "completed"),
            handle_id=str(resumed.get("handle_id") or ""),
            output=str(resumed.get("output") or ""),
            error=resumed.get("error"),
            metadata=dict(resumed.get("metadata") or {}),
        )

    async def _legacy_dispatch(
        self, binding: Binding, inputs: SpawnHarnessIn, ctx: NodeContext
    ) -> Invocation | None:
        """A completed dispatch recorded under this node's previous effect key.

        #1319 changed the key from ``agent.spawn_harness.dispatch:<harness
        type>`` to one that also carries the Run, the graph node and a digest
        of the request. That is the right identity, but it is a *different*
        identity, and the change is not free during a rollout: a deployment
        that upgrades after the adapter dispatched but before the node
        persisted its pause would compute the new key, find no Invocation
        under it, and dispatch the same external harness task a second time.
        The harness has already started work that nothing is tracking.

        So the old key is read first, and only on this Run. Returning its
        recorded result is a replay, not a second effect: the dispatch handle
        it carries is the one the harness actually issued.

        Reads are scoped to the Run, so this cannot resurrect an effect from
        some other Run that happened to use the same harness type -- which the
        old key, carrying nothing but the type, could not distinguish.
        """

        read_history = getattr(self._effects.invocations, "latest_effect", None)
        if read_history is None:
            # A composition that cannot read effect history cannot answer the
            # rollout question either. That is not a reason to refuse the
            # dispatch -- it is the pre-#1319 behaviour, unchanged.
            return None
        legacy = await read_history(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            effect_key=f"agent.spawn_harness.dispatch:{inputs.harness_type}",
            logical_effect=True,
        )
        if not isinstance(legacy, Invocation) or legacy.status is not InvocationStatus.COMPLETED:
            return None
        return legacy

    async def _dispatch(
        self,
        binding: Binding,
        inputs: SpawnHarnessIn,
        ctx: NodeContext,
        *,
        request_payload: dict[str, Any],
        resolver: Any,
        executor: Any,
    ) -> Invocation:
        """The dispatch, replayed from either effect key or newly made."""

        replayed = await self._legacy_dispatch(binding, inputs, ctx)
        if replayed is not None:
            return replayed
        # Include the logical request in the key: a changed task is explicit
        # new work, while a retry with a new NodeRun keeps the same identity.
        effect_key = self.replay_effect_key(inputs, ctx)
        invocation = await invoke_capability_effect(
            lambda: self._effects.invocations.invoke(
                binding=binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key=effect_key,
                request=request_payload,
                resolver=resolver,
                executor=executor,
                logical_effect=True,
            ),
            effect_key=effect_key,
        )
        return invocation

    async def _with_fresh_harness_evidence(
        self, inputs: SpawnHarnessIn, ctx: NodeContext, resumed: Any
    ) -> Any:
        """Prefer the provider's own poll evidence over a transported answer.

        The resume answer may have travelled through a waker or a person; the
        adapter that owns the session can often confirm (or correct) the
        payload directly. A successful poll wins; anything else — no adapter,
        no handle, provider lost the turn — leaves the recorded answer
        untouched, so the answer path stays the fallback, never a blocker.
        """
        adapter = self._adapters.get(inputs.harness_type)
        handle_id = str(resumed.get("handle_id") or "")
        if adapter is None or not handle_id:
            return resumed
        try:
            result = await adapter.poll(
                HarnessHandle(handle_id=handle_id, harness_type=inputs.harness_type)
            )
        except Exception:
            return resumed
        if result is None or not result.success:
            return resumed
        return _merge_poll_evidence(resumed, result)

    async def _execute(self, inputs: SpawnHarnessIn, ctx: NodeContext) -> SpawnHarnessOut:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        resumed = answers.get(ctx.node_id)
        if resumed is not None:
            return self._resume_output(
                await self._with_fresh_harness_evidence(inputs, ctx, resumed)
            )

        if not inputs.binding_id.strip():
            raise BindingNotFound(
                "agent.spawn_harness requires a pre-authorized binding_id before dispatch"
            )

        binding = await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=self.capability,
        )

        request_payload = {
            "harness_type": inputs.harness_type,
            "task": inputs.task,
            "context": inputs.context,
            "timeout_seconds": inputs.timeout_seconds,
            "workdir": inputs.workdir,
        }

        async def resolve_provider(
            authorized: Binding,
        ) -> ResolvedCapabilityProvider | Unavailable:
            adapter = self._adapters.get(inputs.harness_type)
            if adapter is None:
                return Unavailable(
                    slot=self.capability,
                    reason=(
                        f"no harness provider registered for {inputs.harness_type!r}; "
                        f"available={sorted(self._adapters)}"
                    ),
                )
            if authorized.provider_name and authorized.provider_name != inputs.harness_type:
                return Unavailable(
                    slot=self.capability,
                    reason=(
                        f"Binding pins provider {authorized.provider_name!r}, not "
                        f"requested harness provider {inputs.harness_type!r}"
                    ),
                )
            return _HarnessDispatchProvider(name=inputs.harness_type, adapter=adapter)

        async def execute_provider(provider: ResolvedCapabilityProvider, request: Any) -> Any:
            if not isinstance(provider, _HarnessDispatchProvider):
                raise TypeError("harness Invocation resolved a non-harness provider")
            payload = dict(request)
            harness_request = HarnessRequest(
                harness_type=str(payload["harness_type"]),
                task=str(payload["task"]),
                context=dict(payload.get("context") or {}),
                timeout_seconds=int(payload.get("timeout_seconds") or 3600),
                # Workspace hint (issue #1613): the adapter starts the harness
                # session here; the value also lands on the persisted Invocation
                # result so the row records where the harness was pointed.
                metadata={"workdir": str(payload.get("workdir") or "")},
            )
            handle = await provider.adapter.dispatch(harness_request)
            if not handle.handle_id or not handle.harness_type:
                raise RuntimeError("harness provider returned an invalid dispatch handle")
            return {
                "handle_id": handle.handle_id,
                "harness_type": handle.harness_type,
                # Dispatch provenance (issue #1613): harness session id,
                # workspace hint, provider name. Adapter-supplied, so the
                # Invocation row records the session/workspace, not just an
                # opaque handle. A misbehaving adapter's non-dict detail is
                # dropped rather than persisted.
                **_detail_payload(handle),
            }

        invocation = await self._dispatch(
            binding,
            inputs,
            ctx,
            request_payload=request_payload,
            resolver=resolve_provider,
            executor=execute_provider,
        )
        result = invocation.result
        if not isinstance(result, dict):
            raise RuntimeError("completed harness Invocation did not persist a dispatch result")

        pause_until(
            PAUSE_AWAITING_HARNESS,
            metadata={
                "handle_id": str(result["handle_id"]),
                "harness_type": str(result["harness_type"]),
                "binding_id": binding.binding_id,
                "invocation_id": invocation.invocation_id,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        return SpawnHarnessOut()  # unreachable — pause_until raises _NodePaused
