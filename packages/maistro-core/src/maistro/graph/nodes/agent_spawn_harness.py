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

    def logical_effect_key(self, inputs: SpawnHarnessIn, ctx: NodeContext) -> str:
        return replay_effect_key(
            ctx,
            "agent.spawn_harness.dispatch",
            {
                "harness_type": inputs.harness_type,
                "task": inputs.task,
                "context": inputs.context,
                "timeout_seconds": inputs.timeout_seconds,
            },
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

        # The graph may retry this logical node with a new NodeRun. Scope the
        # effect by the stable Run/node/input identity, not that physical visit.
        effect_key = self.logical_effect_key(inputs, ctx)
        invocation = await invoke_capability_effect(
            lambda: self._effects.invocations.invoke(
                binding=binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key=effect_key,
                effect_scope=effect_key,
                request=request_payload,
                resolver=resolve_provider,
                executor=execute_provider,
            ),
            effect_key=effect_key,
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
                # The paused Graph state must retain the same logical-effect
                # identity that admitted the Invocation, not only its first
                # physical row. A resumed/recovered visit can then correlate
                # the wait with the canonical replay contract (#1194).
                "effect_key": effect_key,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        return SpawnHarnessOut()  # unreachable — pause_until raises _NodePaused
