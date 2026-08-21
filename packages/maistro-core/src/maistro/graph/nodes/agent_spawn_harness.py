"""`agent.spawn_harness` — spawn an external agent harness as a DAG node.

Treats any agent harness (Claude Code session, remote Conductor instance,
LangChain agent, generic HTTP endpoint) as a first-class DAG node. On first
execution the node dispatches a task to the harness backend and pauses the
run (durable pause). When the run is resumed with a harness result, the node
returns it.

Backends are injected via the `adapters` map keyed by harness_type string
(e.g. "claude_code", "conductor", "generic_http"). The DI container wires
concrete `HarnessAdapter` implementations; tests inject fakes.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from maistro.graph.harness import HarnessAdapter, HarnessRequest

from . import register_node
from .base import BaseNode, NodeContext, pause_until


class SpawnHarnessIn(BaseModel):
    harness_type: str = Field(
        description="Harness kind: claude_code, conductor, generic_http, in_process"
    )
    task: str = Field(description="Task description handed to the harness")
    context: dict[str, Any] = Field(
        default_factory=dict, description="Additional context for the harness"
    )
    timeout_seconds: int = Field(default=3600, description="Hard deadline in seconds")


class SpawnHarnessOut(BaseModel):
    status: Literal["completed", "failed", "timed_out"] = "completed"
    handle_id: str = ""
    output: str = ""
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@register_node
class AgentSpawnHarnessNode(BaseNode[SpawnHarnessIn, SpawnHarnessOut]):
    """Spawn an external agent harness and pause until it returns a result."""

    kind: ClassVar[str] = "agent.spawn_harness"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = SpawnHarnessIn
    output_schema: ClassVar[type[BaseModel]] = SpawnHarnessOut
    cost_hint: ClassVar[float] = 5.0
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Agent: spawn harness"
    description: ClassVar[str] = (
        "Dispatch a task to an external agent harness (Claude Code, Conductor, HTTP) "
        "and pause the DAG until that harness completes."
    )

    def __init__(self, adapters: dict[str, HarnessAdapter] | None = None) -> None:
        self._adapters: dict[str, HarnessAdapter] = adapters or {}

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

        adapter = self._adapters.get(inputs.harness_type)
        if adapter is None:
            return SpawnHarnessOut(
                status="failed",
                error=(
                    f"No adapter registered for harness_type={inputs.harness_type!r}. "
                    f"Available: {sorted(self._adapters)}"
                ),
            )

        request = HarnessRequest(
            harness_type=inputs.harness_type,
            task=inputs.task,
            context=inputs.context,
            timeout_seconds=inputs.timeout_seconds,
        )
        handle = await adapter.dispatch(request)
        pause_until(
            "awaiting_harness",
            metadata={
                "handle_id": handle.handle_id,
                "harness_type": handle.harness_type,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        return SpawnHarnessOut()  # unreachable — pause_until raises _NodePaused
