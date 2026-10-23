"""`jira.wait_for_subtasks` - governed Jira polling wait node."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
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

#: Host-approved floor for `poll_interval_seconds`. The host, not the DAG
#: author, owns this bound: a zero or negative interval turns the node into a
#: hot loop against an external Jira API (one HTTP poll per wake, waking
#: immediately), and the wake cadence is the runtime's, not the author's, to
#: make safe. Raise it here if external-poll politeness ever demands more.
MIN_POLL_INTERVAL_SECONDS = 5


class WaitForSubtasksIn(BaseModel):
    binding_id: str = Field(description="Pre-authorized Jira Binding for this workspace/project")
    parent_key: str = Field(description="e.g. PROJ-100")
    target_statuses: list[str] = Field(default_factory=lambda: ["Done", "Closed"])
    timeout_seconds: int = Field(
        default=86_400 * 7,
        gt=0,
        description="Overall wait budget in seconds; must be positive.",
    )
    poll_interval_seconds: int = Field(
        default=900,  # 15 min
        ge=MIN_POLL_INTERVAL_SECONDS,
        description=(
            "Seconds between polls; floored by the host at "
            f"{MIN_POLL_INTERVAL_SECONDS} so a bad config cannot request "
            "a hot external polling loop."
        ),
    )
    timeout_s: float = Field(default=8.0, gt=0, description="HTTP timeout per poll")


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
        # A cadence that can never re-check inside the budget is a
        # contradiction between two values the same author configured: with
        # `poll_interval_seconds > timeout_seconds` the node wakes once, after
        # its own deadline has already passed, and reports a timeout it never
        # had a second look to avoid. Enforced here — the single entry every
        # execution reaches — so a failed Attempt names both fields instead of
        # a week-long wait ending in an unexplained timeout.
        if inputs.timeout_seconds < inputs.poll_interval_seconds:
            raise ValueError(
                f"timeout_seconds ({inputs.timeout_seconds}) must be >= "
                f"poll_interval_seconds ({inputs.poll_interval_seconds}) or the "
                "deadline passes before the first poll can re-check"
            )
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

    raw_first_seen = _first_seen(ctx)
    now = now_utc()
    anchor, repair = _resolve_anchor(raw_first_seen, now)

    if raw_first_seen is not None and (now - anchor).total_seconds() >= inputs.timeout_seconds:
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
        "first_seen": anchor.isoformat(),
        "poll_number": poll_number + 1,
    }
    if raw_first_seen is None:
        metadata["deadline"] = (now + timedelta(seconds=inputs.timeout_seconds)).isoformat()
    if repair is not None:
        metadata["first_seen_repair"] = repair
        # Converge the legacy sidecar key onto the same canonical value so a
        # later resume that reads the fallback (no carried pause) finds the
        # repaired anchor, not the corrupt string that caused this.
        if ctx.metadata is not None:
            ctx.metadata[f"wait_first_seen:{ctx.node_id}"] = anchor.isoformat()
    pause_until(
        PAUSE_WAITING_ON_JIRA_SUBTASKS,
        resume_at=now + timedelta(seconds=inputs.poll_interval_seconds),
        metadata=metadata,
    )
    return WaitForSubtasksOut(parent_key=inputs.parent_key)


def _resolve_anchor(raw_first_seen: Any, now: datetime) -> tuple[datetime, dict[str, Any] | None]:
    """The elapsed-time anchor to measure against, and repair evidence if any.

    A missing anchor (true first reach) or an unparseable one both resolve to
    `now`, but only the latter is a repair: the old behaviour substituted
    `now` silently *and re-persisted the corrupt string*, so every evaluation
    reset the elapsed clock and the deadline could never arrive. The repair
    recorded here is explicit and one-shot — the pause carries the canonical
    timestamp plus what it replaced, so the next evaluation reads a parseable
    anchor instead of restarting the clock again.
    """
    if raw_first_seen is None:
        return now, None
    parsed = _parse_first_seen(raw_first_seen)
    if parsed is not None:
        return parsed, None
    repair = {
        "reason": "unparseable_first_seen",
        "replaced": raw_first_seen if isinstance(raw_first_seen, str) else repr(raw_first_seen),
        "repaired_at": now.isoformat(),
    }
    return now, repair


def _parse_first_seen(value: Any) -> datetime | None:
    """Parse a persisted first-seen anchor, or ``None`` if it is corrupt.

    "Corrupt" covers both an unparseable string and a parseable-but-naive
    one: elapsed time is computed against a tz-aware UTC clock, and a naive
    value would make that subtraction a ``TypeError`` mid-poll. Neither
    shape can anchor a deadline, so both route to the same explicit repair
    path instead of one failing loudly and the other crashing the run.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


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
