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
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from maistro.a2a.delegate import A2ADelegator, DelegationMode
from maistro.a2a.guest_peers import GuestPeerManager

from . import register_node
from .base import BaseNode, NodeContext, now_utc, pause_until

if TYPE_CHECKING:
    from maistro.runs.store import RunStore


class DelegationNotConfiguredError(RuntimeError):
    """The node was resolved without the dependency its dispatch path needs.

    A returned `status="failed"` here is indistinguishable from the remote
    agent declining the work, and those are different facts: one is a
    misconfiguration of this instance, the other is a legitimate outcome the
    Graph may branch on. `build_node_resolver` special-cased only
    `agent.spawn_harness` and `rsi.quota_pace_trigger`, so in production this
    node was always constructed with `a2a_delegator=None` and every delegation
    "failed" silently -- the same shape as the stub-LLM success
    `graph_runner.StubLLMNotAllowedError` exists to refuse (#147).
    """


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
    # A destination has to be *nameable* for `RunStore.create_run`'s escape
    # guards to be reachable from this path at all -- its own refusal says
    # "caller must authorize and request the destination Project", and until
    # now no caller could. `None` means the parent's own scope, which is the
    # only thing that succeeds without `allow_cross_project`.
    to_workspace_id: str | None = Field(
        default=None, description="Destination Workspace (None = the delegating Run's)"
    )
    to_project_id: str | None = Field(
        default=None, description="Destination Project (None = the delegating Run's)"
    )


class DelegateRemoteOut(BaseModel):
    """Result of a delegated task once the remote session resumes or fails."""

    status: Literal["completed", "failed", "rejected", "timed_out"] = "completed"
    task_id: str = ""
    #: The canonical child Run. `task_id` stays a receipt of the A2A transport;
    #: this is the execution identity the resumed result correlates to.
    run_id: str = ""
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
        run_store: RunStore | None = None,
    ) -> None:
        """Wire in the delegator, the guest-peer manager and the Run store.

        `run_store` is what turns delegated work into a canonical child Run
        rather than an `A2ATask` with its own competing lifecycle. Optional so
        the node stays constructible in tests that only exercise dispatch, but
        `build_node_resolver` supplies it in production.
        """
        self._a2a_delegator = a2a_delegator
        self._guest_peers = guest_peers
        self._run_store = run_store

    async def _execute(self, inputs: DelegateRemoteIn, ctx: NodeContext) -> DelegateRemoteOut:
        """Dispatch on first run, or return the resumed delegation result."""
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        resumed = answers.get(ctx.node_id)
        if resumed is not None:
            return DelegateRemoteOut(
                status=resumed.get("status", "completed"),
                task_id=str(resumed.get("task_id") or ""),
                run_id=str(resumed.get("run_id") or ""),
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
            msg = (
                "agent.delegate_remote reached a cross-instance dispatch with no "
                "guest_peers manager. This is a wiring fault in this instance, not "
                "a refusal by the remote peer -- see build_node_resolver (#147)."
            )
            raise DelegationNotConfiguredError(msg)

        result = await self._guest_peers.delegate(
            inputs.peer_name or "",
            inputs.from_agent,
            [{"role": "user", "content": inputs.task}],
        )
        if result.status in ("rejected", "failed"):
            # No child Run: nothing was admitted, so there is no execution to
            # give an identity to. The peer declining is a legitimate outcome
            # the Graph may branch on, unlike the misconfiguration above.
            return DelegateRemoteOut(
                status=result.status,
                task_id=result.task_id,
                error=result.error,
            )

        run_id = await self._create_child_run(
            inputs, ctx, task_id=result.task_id, mode="guest_peer"
        )
        self._pause(inputs, task_id=result.task_id, mode="guest_peer", run_id=run_id)
        return DelegateRemoteOut()  # unreachable

    async def _dispatch_in_process(
        self, inputs: DelegateRemoteIn, ctx: NodeContext
    ) -> DelegateRemoteOut:
        """Delegate to another agent in the same Conductor instance, then pause."""
        if self._a2a_delegator is None:
            msg = (
                "agent.delegate_remote reached an in-process dispatch with no "
                "a2a_delegator. This is a wiring fault in this instance, not a "
                "refusal by the target agent -- see build_node_resolver (#147)."
            )
            raise DelegationNotConfiguredError(msg)

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

        run_id = await self._create_child_run(inputs, ctx, task_id=task_id, mode="in_process")
        self._pause(inputs, task_id=task_id, mode="in_process", run_id=run_id)
        return DelegateRemoteOut()  # unreachable

    async def _create_child_run(
        self, inputs: DelegateRemoteIn, ctx: NodeContext, *, task_id: str, mode: str
    ) -> str:
        """File the delegated work as a child Run of the delegating NodeRun.

        This is the point of #147. Before it, delegated work's only identity
        was an `A2ATask` carrying its own `TaskStatus` enum and its own
        `can_transition` table -- a second lifecycle running beside the Run,
        which is what "A2A lifecycle no longer competes with Run after
        admission" is about. The identity needed was already in hand and
        unused: `ctx` carries `run_id` and `node_run_id`, and both dispatch
        methods took `ctx` and never read it.

        The child is filed in the parent's Workspace and Project unless the
        delegation explicitly names another, which is what makes
        `RunStore.create_run`'s two escape guards reachable rather than
        theoretical. Crossing a Project still needs `allow_cross_project`,
        which this never passes -- an implicit cross-Project delegation is
        exactly what the guard refuses, and honouring a request to cross is an
        authorization decision that does not belong in a graph node.

        Returns `""` when no `run_store` was wired, rather than raising: a
        store-less node is a legitimate test construction, and unlike a missing
        delegator it does not make the delegation itself a lie.
        """
        if self._run_store is None:
            return ""

        parent = await self._run_store.get_run(ctx.run_id)
        if parent is None:
            msg = (
                f"agent.delegate_remote ran under run_id {ctx.run_id!r}, which the "
                "Run store does not know. A delegation cannot be filed as a child "
                "of a Run that does not exist."
            )
            raise DelegationNotConfiguredError(msg)

        from maistro.graph.definitions import Graph, Node

        target = inputs.to_agent or inputs.peer_name or "auto"
        graph = Graph(
            workspace_id=inputs.to_workspace_id or parent.workspace_id,
            project_id=inputs.to_project_id or parent.project_id,
            name=f"delegation:{inputs.from_agent or 'unknown'}->{target}",
            nodes=[
                Node(
                    node_type="agent.delegate_remote",
                    name=target,
                    inputs={"task": inputs.task, "to_agent": inputs.to_agent},
                )
            ],
        )
        child = await self._run_store.create_run(
            graph,
            parent_run_id=ctx.run_id,
            parent_node_run_id=ctx.node_run_id or None,
            provenance={
                "admission_source": "a2a_delegation",
                # The A2A task id stays a receipt of the transport rather than
                # the work's identity, the way TaskResponse does for the queue.
                "a2a_task_id": task_id,
                "delegation_mode": mode,
                "delegating_agent": inputs.from_agent,
                "target_agent": target,
                "peer_name": inputs.peer_name,
            },
        )
        return child.run_id

    def _pause(self, inputs: DelegateRemoteIn, *, task_id: str, mode: str, run_id: str) -> None:
        """Checkpoint the DAG until the delegated task completes or times out."""
        resume_at = now_utc() + timedelta(seconds=inputs.timeout_seconds)
        pause_until(
            "awaiting_remote_delegation",
            resume_at=resume_at,
            metadata={
                "task_id": task_id,
                # The resumed result correlates to this, not only to `task_id`:
                # the Run is the execution identity, the A2A task is a receipt
                # of the transport that carried it.
                "run_id": run_id,
                "mode": mode,
                "peer_name": inputs.peer_name,
                "to_agent": inputs.to_agent,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
