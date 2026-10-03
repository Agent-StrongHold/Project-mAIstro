"""`jira.wait_for_subtasks` - governed Jira polling wait node."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.pm_polling import (
    JIRA_SUBTASKS_CAPABILITY,
    JiraSubtasksRequest,
    invoke_jira_poll,
)

from . import register_node
from .base import (
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
    BaseNode,
    NodeContext,
    ReplaySemantics,
    now_utc,
    pause_until,
    resumed_pause,
)


class WaitForSubtasksIn(BaseModel):
    binding_id: str = Field(description="Pre-authorized Jira Binding for this workspace/project")
    parent_key: str = Field(description="e.g. PROJ-100")
    target_statuses: list[str] = Field(default_factory=lambda: ["Done", "Closed"])
    timeout_seconds: int = Field(default=86_400 * 7)
    poll_interval_seconds: int = Field(default=900)
    timeout_s: float = Field(default=8.0, description="HTTP timeout per poll")


class WaitForSubtasksOut(BaseModel):
    parent_key: str
    subtask_keys: list[str] = Field(default_factory=list)
    statuses: dict[str, str] = Field(default_factory=dict)
    all_match: bool = False
    timed_out: bool = False


@register_node
class JiraWaitForSubtasksNode(BaseNode[WaitForSubtasksIn, WaitForSubtasksOut]):
    kind: ClassVar[str] = "jira.wait_for_subtasks"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = WaitForSubtasksIn
    output_schema: ClassVar[type[BaseModel]] = WaitForSubtasksOut
    cost_hint: ClassVar[float] = 1.0
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.IDEMPOTENT
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Jira: wait for subtasks"
    # The resolver must hand over the container's Binding/Invocation authority;
    # the constructor default is a process-wide context that authorizes nothing.
    optional_authorities: ClassVar[Mapping[str, str]] = {"effect_context": "effect_context"}
    description: ClassVar[str] = (
        "Pause until Jira subtasks reach a target status through a governed "
        "Jira capability Binding."
    )

    def __init__(self, *, effect_context: CapabilityEffectContext | None = None) -> None:
        self._effects = effect_context or default_effect_context()

    async def _execute(self, inputs: WaitForSubtasksIn, ctx: NodeContext) -> WaitForSubtasksOut:
        binding = await self._authorized_binding(inputs, ctx)
        poll_number = int(resumed_pause(ctx).get("poll_number", 0) or 0)
        statuses = await _fetch_subtask_statuses(
            inputs,
            ctx=ctx,
            effects=self._effects,
            binding=binding,
            poll_number=poll_number,
        )
        if not statuses or _all_match(statuses, inputs.target_statuses):
            # No subtasks is vacuously satisfied: there is nothing left to wait
            # for, and parking forever on an empty parent is the wrong answer.
            return WaitForSubtasksOut(
                parent_key=inputs.parent_key,
                subtask_keys=list(statuses.keys()),
                statuses=statuses,
                all_match=True,
                timed_out=False,
            )
        return _wait_again_or_time_out(inputs, statuses=statuses, poll_number=poll_number, ctx=ctx)

    async def _authorized_binding(self, inputs: WaitForSubtasksIn, ctx: NodeContext) -> Any:
        """The Binding this poll runs under, refused before any Jira request."""

        if not inputs.binding_id.strip():
            raise BindingNotFound(
                "jira.wait_for_subtasks requires a pre-authorized Binding before any request"
            )
        return await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=JIRA_SUBTASKS_CAPABILITY,
        )


def _all_match(statuses: dict[str, str], target_statuses: Sequence[str]) -> bool:
    """Whether every subtask has reached one of the target statuses."""

    target_lower = {status.lower() for status in target_statuses}
    return all(status.lower() in target_lower for status in statuses.values())


def _wait_again_or_time_out(
    inputs: WaitForSubtasksIn,
    *,
    statuses: dict[str, str],
    poll_number: int,
    ctx: NodeContext,
) -> WaitForSubtasksOut:
    """Park for another interval, or report the deadline as reached.

    The deadline runs from the *first* time this node saw unmatched subtasks,
    carried across pauses, so a resumed Run does not restart the clock and wait
    forever one interval at a time.
    """

    first_seen = _first_seen(ctx)
    now = now_utc()
    if first_seen is not None and (now - _parsed(first_seen, now)).total_seconds() >= (
        inputs.timeout_seconds
    ):
        return WaitForSubtasksOut(
            parent_key=inputs.parent_key,
            subtask_keys=list(statuses.keys()),
            statuses=statuses,
            all_match=False,
            timed_out=True,
        )

    metadata: dict[str, Any] = {
        "parent_key": inputs.parent_key,
        "current_statuses": statuses,
        "first_seen": first_seen if first_seen is not None else now.isoformat(),
        "poll_number": poll_number + 1,
    }
    if first_seen is None:
        metadata["deadline"] = (now + timedelta(seconds=inputs.timeout_seconds)).isoformat()
    pause_until(
        PAUSE_WAITING_ON_JIRA_SUBTASKS,
        resume_at=now + timedelta(seconds=inputs.poll_interval_seconds),
        metadata=metadata,
    )
    return WaitForSubtasksOut(parent_key=inputs.parent_key)


def _parsed(first_seen: Any, fallback: datetime) -> datetime:
    """The carried timestamp, or ``fallback`` when it cannot be read.

    An unreadable timestamp restarts the clock rather than timing the wait out
    immediately: the node's job is to wait, so a corrupt marker must not be
    read as "the deadline already passed".
    """

    try:
        return datetime.fromisoformat(str(first_seen))
    except Exception:
        return fallback


def _first_seen(ctx: NodeContext) -> Any:
    """Read the first-reach timestamp carried by this node's previous pause."""

    carried = resumed_pause(ctx).get("first_seen")
    if carried:
        return carried
    return (ctx.metadata or {}).get(f"wait_first_seen:{ctx.node_id}")


async def _fetch_subtask_statuses(
    inputs: WaitForSubtasksIn,
    *,
    ctx: NodeContext,
    effects: CapabilityEffectContext,
    binding: Any,
    poll_number: int,
) -> dict[str, str]:
    invocation = await invoke_jira_poll(
        effects,
        binding=binding,
        run_id=ctx.run_id,
        node_run_id=ctx.node_run_id,
        attempt_id=ctx.attempt_id,
        effect_key=f"jira.wait_for_subtasks.status:{inputs.parent_key}:{poll_number}",
        request=JiraSubtasksRequest(parent_key=inputs.parent_key),
        timeout_s=inputs.timeout_s,
        actor_id=str(ctx.user_id or ""),
    )
    data = invocation.result if isinstance(invocation.result, dict) else {}
    subtasks = (data.get("fields") or {}).get("subtasks") or []
    result: dict[str, str] = {}
    for subtask in subtasks:
        key = subtask.get("key", "")
        status_name = ((subtask.get("fields") or {}).get("status") or {}).get("name", "")
        if key:
            result[key] = status_name
    return result
