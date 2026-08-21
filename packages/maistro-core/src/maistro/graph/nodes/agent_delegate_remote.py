"""`agent.delegate_remote` — pause while another agent session runs a subgraph.

Treats "wait for a remote agent/Conductor session to finish its subgraph" as
the same pause/resume primitive `human.approve_draft`/`human.ask_question`
use for HITL — the DAG checkpoints, something external runs, and the node
resumes with a result.

Two delegation paths, matching the two delegation models already in
`maistro.a2a` (intentionally not introducing a third):

  - **In-process**: `peer_name` is unset, `subgraph`/`task` describe work for
    another agent in the same Conductor instance. Dispatched via the
    injected `A2ADelegator` (`a2a/delegate.py`).
  - **Cross-instance**: `peer_name` is set, resolved against the injected
    `GuestPeerManager`'s registered `PeerTrust`s (`a2a/guest_peers.py`), and
    dispatched over HTTP to the remote Conductor/session.

Audit trail goes through the existing `AuditLogger` Protocol from
`guest_peers.py` (used only on the cross-instance path, since that's the
only path that already defines one) rather than a new one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from maistro.a2a.delegate import A2ADelegator, DelegationMode
from maistro.a2a.guest_peers import GuestPeerManager

from . import register_node
from .base import BaseNode, NodeContext, now_utc, pause_until


class DelegateRemoteIn(BaseModel):
    """Inputs for dispatching a task to an in-process or cross-instance peer agent."""

    from_agent: str = Field(default="", description="Agent initiating the delegation")
    task: str = Field(default="", description="Task/contract handed to the remote agent")
    peer_name: str | None = Field(
        default=None, description="If set, delegate cross-instance to this registered peer"
    )
    to_agent: str | None = Field(
        default=None, description="In-process: explicit target agent (None = auto-select)"
    )
    subgraph: dict[str, Any] | None = Field(
        default=None, description="Inline subgraph payload for in-process delegation"
    )
    timeout_seconds: int = Field(default=86_400)


class DelegateRemoteOut(BaseModel):
    """Result of a delegated task once the remote session resumes or fails."""

    status: Literal["completed", "failed", "rejected", "timed_out"] = "completed"
    task_id: str = ""
    result: str | None = None
    error: str | None = None
    timed_out: bool = False


@register_node
class AgentDelegateRemoteNode(BaseNode[DelegateRemoteIn, DelegateRemoteOut]):
    """Pause the DAG while another agent session runs a delegated subgraph."""

    kind: ClassVar[str] = "agent.delegate_remote"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = DelegateRemoteIn
    output_schema: ClassVar[type[BaseModel]] = DelegateRemoteOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Agent: delegate to remote session"
    description: ClassVar[str] = (
        "Dispatch a task to another agent session (in-process or a trusted "
        "external peer) and pause until that session's subgraph completes."
    )

    def __init__(
        self,
        *,
        a2a_delegator: A2ADelegator | None = None,
        guest_peers: GuestPeerManager | None = None,
    ) -> None:
        """Wire in the in-process delegator and/or cross-instance guest-peer manager."""
        self._a2a_delegator = a2a_delegator
        self._guest_peers = guest_peers

    async def _execute(self, inputs: DelegateRemoteIn, ctx: NodeContext) -> DelegateRemoteOut:
        """Dispatch on first run, or return the resumed delegation result."""
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        resumed = answers.get(ctx.node_id)
        if resumed is not None:
            return DelegateRemoteOut(
                status=resumed.get("status", "completed"),
                task_id=str(resumed.get("task_id") or ""),
                result=resumed.get("result"),
                error=resumed.get("error"),
                timed_out=bool(resumed.get("timed_out", False)),
            )

        if inputs.peer_name is not None:
            return await self._dispatch_cross_instance(inputs, ctx)
        return await self._dispatch_in_process(inputs, ctx)

    async def _dispatch_cross_instance(
        self, inputs: DelegateRemoteIn, ctx: NodeContext
    ) -> DelegateRemoteOut:
        """Delegate to a trusted external peer via `GuestPeerManager`, then pause."""
        if self._guest_peers is None:
            return DelegateRemoteOut(status="failed", error="no guest_peers manager configured")

        result = await self._guest_peers.delegate(
            inputs.peer_name or "",
            inputs.from_agent,
            [{"role": "user", "content": inputs.task}],
        )
        if result.status in ("rejected", "failed"):
            return DelegateRemoteOut(
                status=result.status,
                task_id=result.task_id,
                error=result.error,
            )

        self._pause(inputs, task_id=result.task_id, mode="guest_peer")
        return DelegateRemoteOut()  # unreachable

    async def _dispatch_in_process(
        self, inputs: DelegateRemoteIn, ctx: NodeContext
    ) -> DelegateRemoteOut:
        """Delegate to another agent in the same Conductor instance, then pause."""
        if self._a2a_delegator is None:
            return DelegateRemoteOut(status="failed", error="no a2a_delegator configured")

        try:
            task_id = self._a2a_delegator.delegate_task(
                inputs.from_agent,
                inputs.task,
                inputs.to_agent,
                delegation_mode=DelegationMode.ALLOW_ALL
                if inputs.to_agent is None
                else DelegationMode.ALLOW_LIST,
            )
        except ValueError as exc:
            return DelegateRemoteOut(status="rejected", error=str(exc))

        self._pause(inputs, task_id=task_id, mode="in_process")
        return DelegateRemoteOut()  # unreachable

    def _pause(self, inputs: DelegateRemoteIn, *, task_id: str, mode: str) -> None:
        """Checkpoint the DAG until the delegated task completes or times out."""
        resume_at = now_utc() + timedelta(seconds=inputs.timeout_seconds)
        pause_until(
            "awaiting_remote_delegation",
            resume_at=resume_at,
            metadata={
                "task_id": task_id,
                "mode": mode,
                "peer_name": inputs.peer_name,
                "to_agent": inputs.to_agent,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
