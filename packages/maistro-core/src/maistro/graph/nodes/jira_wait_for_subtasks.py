"""`jira.wait_for_subtasks` — wait until all subtasks of a parent Jira issue
match a target status (or timeout).

This is a `wait.*` node. On first reach it pauses; the runtime polls the
node periodically; when all subtasks match the target status (Done by
default) it returns successfully. If the parent has no subtasks, it
short-circuits as completed.

The polling cadence + timeout are configurable. When timed out, the result
carries `timed_out=True` so downstream conditional edges can branch.
"""

from __future__ import annotations

from datetime import timedelta
from typing import ClassVar

from pydantic import BaseModel, Field

from maistro.http import shared_client

from . import register_node
from .base import (
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
    BaseNode,
    NodeContext,
    now_utc,
    pause_until,
)


class WaitForSubtasksIn(BaseModel):
    base_url: str
    parent_key: str = Field(description="e.g. PROJ-100")
    pat: str
    flavor: str = Field(default="server")  # "server" | "cloud"
    email: str | None = None
    target_statuses: list[str] = Field(default_factory=lambda: ["Done", "Closed"])
    timeout_seconds: int = Field(default=86_400 * 7)
    poll_interval_seconds: int = Field(default=900)  # 15 min
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
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Jira: wait for subtasks"
    description: ClassVar[str] = (
        "Pause the DAG until all subtasks of a parent issue reach a target "
        "status. Resumes when the condition is met or the timeout fires."
    )

    async def _execute(self, inputs: WaitForSubtasksIn, ctx: NodeContext) -> WaitForSubtasksOut:
        # Check the parent's subtasks right now. If they already match, we
        # complete on first reach; otherwise we pause until the next poll.
        statuses = await _fetch_subtask_statuses(inputs)
        if not statuses:
            # No subtasks — completed.
            return WaitForSubtasksOut(
                parent_key=inputs.parent_key,
                subtask_keys=[],
                statuses={},
                all_match=True,
                timed_out=False,
            )

        target_lower = {s.lower() for s in inputs.target_statuses}
        all_match = all(s.lower() in target_lower for s in statuses.values())

        if all_match:
            return WaitForSubtasksOut(
                parent_key=inputs.parent_key,
                subtask_keys=list(statuses.keys()),
                statuses=statuses,
                all_match=True,
                timed_out=False,
            )

        # Have we exceeded the overall timeout?
        first_seen = (ctx.metadata or {}).get(f"wait_first_seen:{ctx.node_id}")
        now = now_utc()
        if first_seen is None:
            # First reach — store start timestamp, pause for the poll interval.
            pause_until(
                PAUSE_WAITING_ON_JIRA_SUBTASKS,
                resume_at=now + timedelta(seconds=inputs.poll_interval_seconds),
                metadata={
                    "parent_key": inputs.parent_key,
                    "current_statuses": statuses,
                    "first_seen": now.isoformat(),
                    "deadline": (now + timedelta(seconds=inputs.timeout_seconds)).isoformat(),
                },
            )
            return WaitForSubtasksOut(parent_key=inputs.parent_key)

        # Resume path — was the deadline reached?
        try:
            from datetime import datetime as _dt

            first = _dt.fromisoformat(first_seen)
        except Exception:
            first = now
        if (now - first).total_seconds() >= inputs.timeout_seconds:
            return WaitForSubtasksOut(
                parent_key=inputs.parent_key,
                subtask_keys=list(statuses.keys()),
                statuses=statuses,
                all_match=False,
                timed_out=True,
            )

        # Still waiting — pause for another poll interval.
        pause_until(
            PAUSE_WAITING_ON_JIRA_SUBTASKS,
            resume_at=now + timedelta(seconds=inputs.poll_interval_seconds),
            metadata={
                "parent_key": inputs.parent_key,
                "current_statuses": statuses,
                "first_seen": first_seen,
            },
        )
        return WaitForSubtasksOut(parent_key=inputs.parent_key)


async def _fetch_subtask_statuses(inputs: WaitForSubtasksIn) -> dict[str, str]:
    """Return {subtask_key: status_name} for the parent issue."""
    base = inputs.base_url.rstrip("/")
    api_path = (
        f"/rest/api/2/issue/{inputs.parent_key}"
        if inputs.flavor == "server"
        else f"/rest/api/3/issue/{inputs.parent_key}"
    )
    headers: dict[str, str] = {"Accept": "application/json"}
    auth: tuple[str, str] | None = None
    if inputs.flavor == "server":
        headers["Authorization"] = f"Bearer {inputs.pat}"
    else:
        if inputs.email:
            auth = (inputs.email, inputs.pat)
        else:
            headers["Authorization"] = f"Bearer {inputs.pat}"

    async with shared_client(timeout=inputs.timeout_s) as client:
        resp = await client.get(
            f"{base}{api_path}",
            params={"fields": "subtasks"},
            headers=headers,
            auth=auth,
        )
    if resp.status_code == 401:
        raise PermissionError(f"jira_auth_failed status=401 base={base}")
    if resp.status_code >= 400:
        raise RuntimeError(f"jira_http_error status={resp.status_code}")

    data = resp.json()
    subtasks = (data.get("fields") or {}).get("subtasks") or []
    result: dict[str, str] = {}
    for st in subtasks:
        key = st.get("key", "")
        status_name = ((st.get("fields") or {}).get("status") or {}).get("name", "")
        if key:
            result[key] = status_name
    return result
