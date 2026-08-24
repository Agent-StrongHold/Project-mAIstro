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
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from pydantic import BaseModel, Field

from maistro.a2a.delegate import A2ADelegator, DelegationMode
from maistro.a2a.guest_peers import GuestPeerManager

from . import register_node
from .base import BaseNode, NodeContext, now_utc, pause_until

if TYPE_CHECKING:
    from maistro.graph.definitions import Graph
    from maistro.runs.model import Run
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


#: The outcomes a delegation can report. Named once so the output schema, the
#: terminal-state map and the coercion below cannot drift apart.
DelegationStatus = Literal["completed", "failed", "rejected", "timed_out"]

#: How a delegate's answer maps onto the child Run's terminal state, and whether
#: reaching it has to pass through `running`. `RUN_TRANSITIONS` allows
#: `queued -> timed_out` directly; `completed` and `failed` are only reachable
#: from `running`. Values are `RunStatus` *names*, resolved at use, so this
#: module does not import the runs package at import time.
_CHILD_OUTCOME: dict[str, tuple[str, bool]] = {
    "completed": ("completed", True),
    "failed": ("failed", True),
    "timed_out": ("timed_out", False),
    # The delegate took the work and then declined it. `cancelled` says that
    # more honestly than `failed`, which would read as the work having been
    # attempted and gone wrong.
    "rejected": ("cancelled", False),
}

#: Node kind recorded for delegated work whose shape this instance does not
#: know. Deliberately *not* `agent.delegate_remote`: a child snapshot naming
#: this node describes the dispatch rather than the work, and replaying it
#: would delegate a second time.
_OPAQUE_DELEGATED_WORK = "agent.remote_work"


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

    status: DelegationStatus = "completed"
    task_id: str = ""
    #: The canonical child Run. `task_id` stays a receipt of the A2A transport;
    #: this is the execution identity the resumed result correlates to.
    run_id: str = ""
    result: str | None = None
    error: str | None = None
    timed_out: bool = False


def _coerce_status(raw: str) -> DelegationStatus:
    """Narrow a submitted status to one this node knows how to settle."""
    if raw in _CHILD_OUTCOME:
        return cast(DelegationStatus, raw)
    return "failed"


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
            return await self._resume(resumed)

        if inputs.peer_name is not None:
            return await self._dispatch_cross_instance(inputs, ctx)
        return await self._dispatch_in_process(inputs, ctx)

    async def _resume(self, resumed: dict[str, Any]) -> DelegateRemoteOut:
        """Settle the child Run, then report what the delegate answered.

        The Run id comes from `resumed["_pause"]`, which the store stamps from
        the pause *this node* wrote, never from the submitted answer. The
        responder is the party being waited on; letting it name the execution
        identity it is answering for would let any caller redirect the outcome
        onto someone else's Run. The submitted `run_id`, if there is one, is
        ignored rather than compared -- there is nothing to gain from a
        mismatch except a second way to be wrong.
        """
        pause = resumed.get("_pause")
        run_id = str(pause.get("run_id") or "") if isinstance(pause, dict) else ""
        raw_status = str(resumed.get("status", "completed"))
        status = _coerce_status(raw_status)
        error = resumed.get("error")
        if status != raw_status:
            # The status also selects the child's terminal state, so an
            # unrecognised one would otherwise `KeyError` in the middle of
            # settling a Run. Reporting it as failed *and saying why* keeps a
            # malformed answer from reading as a legitimate refusal.
            error = f"delegate returned an unrecognised status {raw_status!r}"
        out = DelegateRemoteOut(
            status=status,
            task_id=str(resumed.get("task_id") or ""),
            run_id=run_id,
            result=resumed.get("result"),
            error=error,
            timed_out=bool(resumed.get("timed_out", False)),
        )
        await self._terminalize_child(run_id, out)
        return out

    async def _terminalize_child(self, run_id: str, out: DelegateRemoteOut) -> None:
        """Walk the child Run from `created` to the outcome the delegate reported.

        Without this the child is persisted `created` and stays there forever:
        neither A2A transport touches the Run store, so a completed, failed or
        timed-out answer advanced the parent graph while the canonical child
        still claimed it had not begun. That is the same "second lifecycle
        beside the Run" this node exists to remove, one level down.

        The ladder is walked rather than jumped because `RUN_TRANSITIONS` has no
        edge from `created` to a terminal state, and widening it for this caller
        would weaken the invariant for every other one.

        `started_at` therefore marks when the result was reconciled, not when
        the delegate began: no A2A transport reports a start. Stamping the
        dispatch time instead would be a different lie with a more convincing
        shape.
        """
        if self._run_store is None or not run_id:
            return

        from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus

        child = await self._run_store.get_run(run_id)
        if child is None or child.status in TERMINAL_RUN_STATUSES:
            # A store that forgot the child, or a duplicate resume. Neither is
            # this node's to repair, and neither should sink a delegation whose
            # answer is already in hand.
            return

        target_name, via_running = _CHILD_OUTCOME[out.status]
        await self._run_store.transition_run(run_id, RunStatus.QUEUED)
        if via_running:
            await self._run_store.transition_run(run_id, RunStatus.RUNNING)
        await self._run_store.transition_run(
            run_id,
            RunStatus(target_name),
            result=out.result,
            error=out.error,
        )

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

        parent = await self._preflight_child_scope(inputs, ctx)

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
            inputs,
            ctx,
            parent=parent,
            task_id=result.task_id,
            mode="guest_peer",
            target=inputs.peer_name or "",
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

        parent = await self._preflight_child_scope(inputs, ctx)

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

        run_id = await self._create_child_run(
            inputs,
            ctx,
            parent=parent,
            task_id=task_id,
            mode="in_process",
            target=self._admitted_target(task_id, inputs),
        )
        self._pause(inputs, task_id=task_id, mode="in_process", run_id=run_id)
        return DelegateRemoteOut()  # unreachable

    def _admitted_target(self, task_id: str, inputs: DelegateRemoteIn) -> str:
        """The agent the delegator actually chose, not the request that was made.

        With `to_agent=None`, `A2ADelegator.delegate_task` selects a concrete
        agent from the delegator's capabilities. Recording the literal `"auto"`
        left the child's name and `provenance["target_agent"]` disagreeing with
        the admitted `A2ATask.to_agent`, so audit and routing analysis were
        wrong for *every* automatic delegation -- the case the field is most
        needed for.

        Falls back to the requested value if the task cannot be read back: a
        delegator that does not expose its queue is a weaker record, not a
        reason to refuse work that has already been admitted.
        """
        if self._a2a_delegator is not None:
            task = self._a2a_delegator.get_task_status(task_id)
            if task is not None and task.to_agent:
                return str(task.to_agent)
        return inputs.to_agent or "auto"

    async def _preflight_child_scope(
        self, inputs: DelegateRemoteIn, ctx: NodeContext
    ) -> Run | None:
        """Settle whether a child Run is admissible *before* dispatching anything.

        `_create_child_run` used to run after the transport call, so a
        delegation naming a foreign Workspace was refused only once the HTTP
        request had gone out or the `A2ATask` had been queued: the node reported
        failure while unauthorized work carried on elsewhere, and a retry
        dispatched it again. The guard is the same one `create_run` enforces --
        `validate_child_scope`, called from both -- rather than a copy that
        could drift into being the weaker of the two.

        Returns the parent Run so the dispatch path does not fetch it twice, or
        `None` when no store is wired.
        """
        if self._run_store is None:
            return None

        from maistro.runs.store import validate_child_scope

        parent = await self._run_store.get_run(ctx.run_id)
        if parent is None:
            msg = (
                f"agent.delegate_remote ran under run_id {ctx.run_id!r}, which the "
                "Run store does not know. A delegation cannot be filed as a child "
                "of a Run that does not exist."
            )
            raise DelegationNotConfiguredError(msg)

        validate_child_scope(
            parent,
            workspace_id=inputs.to_workspace_id or parent.workspace_id,
            project_id=inputs.to_project_id or parent.project_id,
        )
        return parent

    async def _create_child_run(
        self,
        inputs: DelegateRemoteIn,
        ctx: NodeContext,
        *,
        parent: Run | None,
        task_id: str,
        mode: str,
        target: str,
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

        The delegating actor and persona are carried onto the child rather than
        left `None`: they were already on the parent record, and delegated work
        that loses its attribution cannot be audited or policed as the same
        person's.

        Returns `""` when no `run_store` was wired, rather than raising: a
        store-less node is a legitimate test construction, and unlike a missing
        delegator it does not make the delegation itself a lie.
        """
        if self._run_store is None or parent is None:
            return ""

        graph = self._child_graph(inputs, parent=parent, target=target)
        child = await self._run_store.create_run(
            graph,
            parent_run_id=ctx.run_id,
            parent_node_run_id=ctx.node_run_id or None,
            persona_id=parent.persona_id,
            actor_principal_id=parent.actor_principal_id,
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

    def _child_graph(self, inputs: DelegateRemoteIn, *, parent: Run, target: str) -> Graph:
        """The Graph snapshot the child Run carries: the work, not the dispatch.

        The first version filed every child with a single `agent.delegate_remote`
        node. Inspecting the canonical child then described *another* dispatch
        instead of the work that was admitted, and executing or replaying that
        snapshot would have delegated a second task.

        When the delegation carries an inline `subgraph`, that is the work, and
        it is snapshotted as given -- rescoped into the child's Workspace and
        Project, since a Graph must agree with the Run that holds it. Otherwise
        the shape is genuinely unknown to this instance (the peer holds it), and
        the child records one opaque node naming the delegated task rather than
        a plausible-looking graph nobody can replay.
        """
        from maistro.graph.definitions import Graph, Node

        workspace_id = inputs.to_workspace_id or parent.workspace_id
        project_id = inputs.to_project_id or parent.project_id
        name = f"delegation:{inputs.from_agent or 'unknown'}->{target or 'unknown'}"

        if inputs.subgraph:
            payload = {
                **inputs.subgraph,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "name": inputs.subgraph.get("name") or name,
            }
            return Graph.model_validate(payload)

        return Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            nodes=[
                Node(
                    node_type=_OPAQUE_DELEGATED_WORK,
                    name=target,
                    inputs={
                        "task": inputs.task,
                        "from_agent": inputs.from_agent,
                        "to_agent": target,
                        "peer_name": inputs.peer_name,
                    },
                )
            ],
        )

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
