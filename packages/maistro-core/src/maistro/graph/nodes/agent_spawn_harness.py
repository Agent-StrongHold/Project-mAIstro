"""`agent.spawn_harness` — spawn an external agent harness as a governed DAG effect.

A harness adapter remains provider-specific: it knows how to dispatch to Claude
Code, another Conductor, an in-process harness, or a generic HTTP endpoint. It
does not own universal effect lifecycle or authorization. First dispatch now
resolves a canonical Workspace/Project-scoped Binding and crosses the governed
Invocation boundary before the physical adapter call. The node then pauses the
canonical Run until the harness result is supplied on resume.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.types import Unavailable
from maistro.graph.harness import HarnessAdapter, HarnessRequest

from . import register_node
from .base import (
    PAUSE_AWAITING_HARNESS,
    BaseNode,
    NodeContext,
    pause_until,
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
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = SpawnHarnessIn
    output_schema: ClassVar[type[BaseModel]] = SpawnHarnessOut
    cost_hint: ClassVar[float] = 5.0
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Agent: spawn harness"
    description: ClassVar[str] = (
        "Dispatch a task to an authorized external agent-harness provider through "
        "canonical Binding/Invocation semantics and pause until it completes."
    )
    capability: ClassVar[str] = "harness_runner"

    def __init__(
        self,
        adapters: dict[str, HarnessAdapter] | None = None,
        *,
        effect_context: CapabilityEffectContext | None = None,
    ) -> None:
        self._adapters: dict[str, HarnessAdapter] = adapters or {}
        self._effects = effect_context or default_effect_context()

    async def _execute(self, inputs: SpawnHarnessIn, ctx: NodeContext) -> SpawnHarnessOut:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        resumed = answers.get(ctx.node_id)
        if resumed is not None:
            return SpawnHarnessOut(
                status=resumed.get("status", "completed"),
                handle_id=str(resumed.get("handle_id") or ""),
                output=str(resumed.get("output") or ""),
                error=resumed.get("error"),
                metadata=dict(resumed.get("metadata") or {}),
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
            )
            handle = await provider.adapter.dispatch(harness_request)
            if not handle.handle_id or not handle.harness_type:
                raise RuntimeError("harness provider returned an invalid dispatch handle")
            return {
                "handle_id": handle.handle_id,
                "harness_type": handle.harness_type,
            }

        effect_key = f"agent.spawn_harness.dispatch:{inputs.harness_type}"
        invocation = await invoke_capability_effect(
            lambda: self._effects.invocations.invoke(
                binding=binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key=effect_key,
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
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        return SpawnHarnessOut()  # unreachable — pause_until raises _NodePaused
