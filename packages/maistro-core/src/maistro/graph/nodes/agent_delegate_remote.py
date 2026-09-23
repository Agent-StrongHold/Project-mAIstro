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

<<<<<<< HEAD
=======
import hashlib
import json
>>>>>>> ba2f1f077fd2790c704101ea5435cbb4c2ba78b0
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NoReturn, cast

from pydantic import BaseModel, Field

from maistro.a2a.delegate import A2ADelegator, DelegationMode
<<<<<<< HEAD
from maistro.a2a.guest_peers import GuestPeerManager
from maistro.runs.model import AcceptedNodeOutcome, AttemptResult, AttemptStatus, RunStatus
=======
from maistro.a2a.guest_peers import DelegationResult, GuestPeerManager
>>>>>>> ba2f1f077fd2790c704101ea5435cbb4c2ba78b0

from . import register_node
from .base import (
    PAUSE_AWAITING_DELEGATION_RECONCILIATION,
    PAUSE_AWAITING_REMOTE_DELEGATION,
    BaseNode,
    KindCategory,
    NodeContext,
    now_utc,
    pause_until,
)

if TYPE_CHECKING:
    from maistro.graph.definitions import Graph
    from maistro.runs.model import Run
    from maistro.runs.store import RunStore


class DelegationReconciliationExpired(RuntimeError):
    """The reconciliation window closed without recovering the reserved child.

    A dispatch whose transport acceptance is unknown is retried by polling, not
    completed. When the polling window -- the delegation's own timeout, counted
    from the durable child's creation -- closes without a receipt, the node
    fails: the parent must not advance past work that may still be running
    elsewhere, and a silent advance is exactly what completing an `uncertain`
    output used to do.
    """


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


#: How long a reconciliation pause waits before re-entering the node to look
#: for the missing receipt again. A constant rather than an input: the cadence
#: is recovery plumbing, not a policy the delegating graph chooses, and the
#: window it polls within is the delegation's own `timeout_seconds`.
_RECONCILIATION_POLL = timedelta(seconds=60)

#: The outcomes a delegation can report. Named once so the output schema, the
#: terminal-state map and the coercion below cannot drift apart.
DelegationStatus = Literal["completed", "failed", "rejected", "timed_out", "uncertain"]

#: Statuses accepted from a remote responder. The response remains a receipt
#: projection; the canonical child lifecycle is persisted through RunStore.
_KNOWN_DELEGATION_STATUSES = frozenset({"completed", "failed", "rejected", "timed_out"})
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


class RemoteWorkOut(BaseModel):
    """Output schema for the externally executed opaque work node."""

    status: DelegationStatus = "completed"
    result: str | None = None


@register_node
class AgentRemoteWorkNode(BaseNode[DelegateRemoteIn, RemoteWorkOut]):
    """Catalog the external work represented by a delegation child Run.

    The transport coordinator records the physical Attempt and applies the
    remote answer; replaying this snapshot locally must refuse rather than
    dispatching the same work a second time.
    """

    kind: ClassVar[str] = _OPAQUE_DELEGATED_WORK
    kind_category: ClassVar[KindCategory] = "wait"
    input_schema: ClassVar[type[BaseModel]] = DelegateRemoteIn
    output_schema: ClassVar[type[BaseModel]] = RemoteWorkOut
    display_name: ClassVar[str] = "Agent: delegated external work"
    description: ClassVar[str] = "An opaque child Run whose work executes at an A2A peer."
    external_io: ClassVar[bool] = True

    async def _execute(self, inputs: DelegateRemoteIn, ctx: NodeContext) -> RemoteWorkOut:
        raise DelegationNotConfiguredError(
            "agent.remote_work is an external delegation projection and cannot be replayed locally"
        )


def _coerce_status(raw: str) -> DelegationStatus:
    """Narrow a submitted status to one this node knows how to settle."""
    if raw in _KNOWN_DELEGATION_STATUSES:
        return cast(DelegationStatus, raw)
    return "failed"


@register_node
class AgentDelegateRemoteNode(BaseNode[DelegateRemoteIn, DelegateRemoteOut]):
    """Pause the DAG while another agent session runs a delegated subgraph."""

    kind: ClassVar[str] = "agent.delegate_remote"
    # Optional rather than required, pinned by ADR-082526-3ca6/AC-2: a caller
    # supplying nothing gets an unwired node whose *NodeResult* fails with "no
    # a2a_delegator configured" — the misconfiguration is visible as the node
    # failing, never as the target agent declining.
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "a2a_delegator": "a2a_delegator",
        "guest_peers": "guest_peers",
        "run_store": "run_store",
    }
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

    def _delegation_key(self, _inputs: DelegateRemoteIn, ctx: NodeContext) -> str:
        """Stable identity for one parent NodeRun's logical delegation.

        The request is not part of the key. A retry may deserialize equivalent
        inputs differently, or receive a changed payload after a crash, but it
        must still adopt the child reservation already made for this parent
        NodeRun. The request details remain durable on the child graph and
        provenance; they are not a second admission identity.
        """
        payload = {
            "run_id": ctx.run_id,
            "node_run_id": ctx.node_run_id or None,
            "node_id": ctx.node_id,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _existing_child(self, key: str) -> Run | None:
        if self._run_store is None:
            return None
        return await self._run_store.find_delegation_run(key)

    async def _reserve_child(
        self,
        inputs: DelegateRemoteIn,
        ctx: NodeContext,
        *,
        parent: Run | None,
        mode: str,
        target: str,
    ) -> str:
        """Reserve once; a concurrent replica adopts the unique-key winner."""
        try:
            return await self._create_child_run(
                inputs, ctx, parent=parent, task_id="", mode=mode, target=target
            )
        except Exception:
            existing = await self._existing_child(self._delegation_key(inputs, ctx))
            if existing is None:
                raise
            return existing.run_id

    async def _release_unaccepted_child(self, run_id: str) -> None:
        if not run_id or self._run_store is None:
            return
        await self._run_store.delete_run(run_id, force=True)

    async def _attach_receipt(
        self, run_id: str, task_id: str, *, target: str | None = None
    ) -> Run | None:
        if self._run_store is None:
            # Store-less construction remains useful for transport unit tests;
            # production resolution always supplies the canonical store.
            return None
        return await self._run_store.attach_delegation_receipt(run_id, task_id, target_agent=target)

    async def _claim_transport_attempt(self, run_id: str) -> bool:
        """Durably claim the boundary so concurrent recovery cannot both dispatch."""
        if self._run_store is None:
            return True
        return await self._run_store.claim_delegation_transport_attempt(run_id)

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
        run_id = ""
        if isinstance(pause, Mapping):
            # Durable answer submission stamps the complete server-authored
            # pause entry, whose node metadata carries the child identity.
            # Keep accepting the flat shape used by older callers/tests, but
            # never source the identity from the answer's top-level fields.
            pause_metadata = pause.get("metadata")
            if isinstance(pause_metadata, Mapping):
                run_id = str(pause_metadata.get("run_id") or "")
            if not run_id:
                run_id = str(pause.get("run_id") or "")
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
        await self._record_child_outcome(run_id, out)
        return out

    async def _record_child_outcome(self, run_id: str, out: DelegateRemoteOut) -> None:
        """Record the answer as a physical Attempt and reconcile the child.

        A child Run is admitted with opaque NodeRuns whose first Attempts are
        yielded while the A2A receipt is outstanding. A response creates a new
        Attempt, because yielded Attempts are terminal evidence, then accepts
        that evidence into the NodeRun. This keeps the universal
        Run -> NodeRun -> Attempt hierarchy intact without making A2ATask a
        second execution authority.
        """
        if self._run_store is None or not run_id:
            return

        from maistro.runs.model import TERMINAL_RUN_STATUSES
        from maistro.runs.reconciliation import AttemptLifecycleReconciler

        child = await self._run_store.get_run(run_id)
        if child is None or child.status in TERMINAL_RUN_STATUSES:
            return
        node_runs = await self._run_store.list_node_runs(run_id)
        if not node_runs:
            raise DelegationNotConfiguredError(
                f"child Run {run_id!r} has no NodeRun for its delegated work"
            )
        open_node_runs = [
            node_run for node_run in node_runs if node_run.status not in TERMINAL_RUN_STATUSES
        ]
        if not open_node_runs:
            return

        lifecycle = AttemptLifecycleReconciler(self._run_store)
        cancelled_node_runs: list[str] = []
        for node_run in open_node_runs:
            await lifecycle.prepare_execution(node_run.node_run_id)
            attempt = await self._run_store.create_attempt(
                node_run.node_run_id,
                runtime_id="a2a",
                executor_id=f"agent.delegate_remote:{out.status}",
            )
            token = attempt.execution_lease.fencing_token if attempt.execution_lease else None
            attempt = await self._run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.RUNNING,
                fencing_token=token,
            )

            if out.status == "rejected":
                attempt = await self._run_store.transition_attempt(
                    attempt.attempt_id,
                    AttemptStatus.CANCELLED,
                    error=out.error,
                    fencing_token=token,
                )
                # Reconcile after all siblings are marked, otherwise the first
                # cancellation would terminalize the Run while later NodeRuns
                # still need their evidence recorded.
                cancelled_node_runs.append(node_run.node_run_id)
                continue

            # The peer's response is a completed transport Attempt. The logical
            # projection distinguishes a successful result from a remote
            # failure while preserving the four-value DelegateRemoteOut contract.
            attempt = await self._run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.COMPLETED,
                result={"status": out.status, "task_id": out.task_id, "result": out.result},
                error=out.error,
                fencing_token=token,
            )
            accepted = AcceptedNodeOutcome(
                node_run_id=node_run.node_run_id,
                attempt_result=AttemptResult.from_attempt(attempt),
                logical_status=(
                    RunStatus.COMPLETED if out.status == "completed" else RunStatus.FAILED
                ),
                result=out.result if out.status == "completed" else None,
                error=out.error,
            )
            await lifecycle.accept_outcome(accepted)

        if cancelled_node_runs:
            for node_run_id in cancelled_node_runs:
                await self._run_store.transition_node_run(
                    node_run_id, RunStatus.CANCELLED, error=out.error
                )
            await self._run_store.transition_run(run_id, RunStatus.CANCELLED, error=out.error)

    async def _recover_cross_instance(
        self, inputs: DelegateRemoteIn, key: str, child_id: str
    ) -> DelegateRemoteOut:
        """Reconcile a claimed boundary without submitting a second request."""
        assert self._guest_peers is not None
        assert self._run_store is not None
        current = await self._run_store.get_run(child_id)
        receipt = str(current.provenance.get("a2a_task_id") or "") if current else ""
        if receipt:
            self._pause(inputs, task_id=receipt, mode="guest_peer", run_id=child_id)
            return DelegateRemoteOut()
        reconciled = await self._guest_peers.reconcile(inputs.peer_name or "", key)
        if reconciled.status == "submitted" and reconciled.task_id:
            await self._attach_receipt(child_id, reconciled.task_id)
            self._pause(inputs, task_id=reconciled.task_id, mode="guest_peer", run_id=child_id)
            return DelegateRemoteOut()
        await self._pause_for_reconciliation(
            inputs,
            child_id,
            error=reconciled.error or "transport acceptance is uncertain; reconcile required",
        )

    @staticmethod
    def _mode_for(inputs: DelegateRemoteIn) -> DelegationMode:
        """The delegation mode an explicit `to_agent` implies."""
        return DelegationMode.ALLOW_ALL if inputs.to_agent is None else DelegationMode.ALLOW_LIST

    async def _pause_for_reconciliation(
        self, inputs: DelegateRemoteIn, child_id: str, *, error: str
    ) -> NoReturn:
        """Park the node on a missing receipt instead of completing the dispatch.

        An `uncertain` *output* is a lie the executor believes: `BaseNode.run`
        wraps a normal return as a completed Attempt and the frontier advances,
        so the second invocation the recovery paths assume never happens and
        the reserved child stays `created` without a receipt forever. A
        reconciliation pause is the honest shape: system-owned, so the Run
        parks WAITING, and elapsed-timer resumable, so the resume tick
        re-enters this node and the recovery paths re-read the receipt sources
        rather than re-dispatching.

        The window is the delegation's own `timeout_seconds`, counted from the
        child's durable creation rather than from any pause metadata, so the
        deadline survives restarts, replica moves and retry visits unchanged.
        When it closes without a receipt the child is settled failed and the
        node raises: a reservation nobody could reconcile is a failed
        delegation, not a completed one.

        Always raises (pause or expiry) -- the caller has no outcome to return.
        """
        assert self._run_store is not None
        child = await self._run_store.get_run(child_id)
        created = child.created_at if child is not None else now_utc()
        deadline = created + timedelta(seconds=inputs.timeout_seconds)
        now = now_utc()
        if now >= deadline:
            message = (
                "delegation acceptance could not be reconciled before the "
                f"delegation timeout: {error}"
            )
            await self._terminalize_child(
                child_id, DelegateRemoteOut(status="failed", error=message)
            )
            raise DelegationReconciliationExpired(message)
        pause_until(
            PAUSE_AWAITING_DELEGATION_RECONCILIATION,
            resume_at=min(now + _RECONCILIATION_POLL, deadline),
            metadata={
                "child_run_id": child_id,
                "peer_name": inputs.peer_name,
                "error": error,
            },
        )

    async def _pause_on_existing_receipt(
        self, inputs: DelegateRemoteIn, child: Run, child_id: str, *, mode: str
    ) -> bool:
        """Resume a delegation whose transport receipt is already durable.

        True when the node paused on the recorded receipt (the caller must
        return immediately); False when the child exists but the boundary was
        never crossed and dispatch must still claim it.
        """
        receipt = str(child.provenance.get("a2a_task_id") or "")
        if receipt:
            self._pause(inputs, task_id=receipt, mode=mode, run_id=child_id)
            return True
        return False

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
        key = self._delegation_key(inputs, ctx)
        child = await self._existing_child(key)
        if child is None:
            child_id = await self._reserve_child(
                inputs, ctx, parent=parent, mode="guest_peer", target=inputs.peer_name or ""
            )
        else:
            child_id = child.run_id
            if await self._pause_on_existing_receipt(inputs, child, child_id, mode="guest_peer"):
                return DelegateRemoteOut()

        claimed = await self._claim_transport_attempt(child_id)
        if not claimed:
            # Another replica may have crossed the boundary while this one was
            # reserving the same child. Reconcile; never POST a second time.
            return await self._recover_cross_instance(inputs, key, child_id)

        result = await self._submit_to_peer(inputs, key)
        if result.status == "rejected":
            await self._release_unaccepted_child(child_id)
            # No child Run: nothing was admitted, so there is no execution to
            # give an identity to. The peer declining is a legitimate outcome
            # the Graph may branch on, unlike the misconfiguration above.
            return DelegateRemoteOut(status="rejected", task_id=result.task_id, error=result.error)
        failure = await self._failed_transport_outcome(inputs, child_id, result)
        if failure is not None:
            return failure
        if not result.task_id:
            await self._pause_for_reconciliation(
                inputs,
                child_id,
                error="peer accepted work without a transport receipt",
            )
        if result.status != "submitted" or not result.task_id:
            # A submitted delegation without a receipt cannot be resumed or
            # correlated to the child Run. Treat the peer response as a
            # protocol failure rather than pausing an untraceable execution.
            return DelegateRemoteOut(
                status="failed",
                task_id=result.task_id,
                error=(result.error or "peer returned an invalid delegation receipt"),
            )

        await self._attach_receipt(child_id, result.task_id)
        self._pause(inputs, task_id=result.task_id, mode="guest_peer", run_id=child_id)
        return DelegateRemoteOut()  # unreachable

    async def _submit_to_peer(self, inputs: DelegateRemoteIn, key: str) -> DelegationResult:
        """POST the task to the peer, keyed only when receipts can be stored.

        The idempotency key rides on the request only when a Run store is
        wired: without one the receipt cannot be made durable across a
        restart, so an unkeyed attempt is the honest shape.
        """
        assert self._guest_peers is not None
        messages = [{"role": "user", "content": inputs.task}]
        if self._run_store is None:
            # Preserve the transport-only construction used by callers that do
            # not have canonical admission available; it cannot claim durable
            # recovery semantics, so it must not pretend to send a key.
            return await self._guest_peers.delegate(
                inputs.peer_name or "", inputs.from_agent, messages
            )
        return await self._guest_peers.delegate(
            inputs.peer_name or "",
            inputs.from_agent,
            messages,
            idempotency_key=key,
        )

    async def _failed_transport_outcome(
        self, inputs: DelegateRemoteIn, child_id: str, result: DelegationResult
    ) -> DelegateRemoteOut | None:
        """The outcome for a transport failure, or None when none applies.

        Once a request crossed the transport boundary, an exception does not
        prove that the peer did not accept it. Keep the reservation and park on
        reconciliation; a retry must not blindly POST again. Without a Run
        store nothing durable is at stake, so the failure is reported as the
        delegation outcome it is.
        """
        if result.status != "failed":
            return None
        if self._run_store is not None:
            await self._pause_for_reconciliation(
                inputs,
                child_id,
                error=result.error or "transport acceptance is uncertain",
            )
        return DelegateRemoteOut(status="failed", task_id=result.task_id, error=result.error)

    async def _recover_in_process(
        self, inputs: DelegateRemoteIn, key: str, child_id: str
    ) -> DelegateRemoteOut:
        """Reconcile a claimed boundary against the local task map.

        A durable claim without a receipt means another worker may have
        accepted work and died before attaching it. The local task map is
        the only receipt authority available; absent that, stay
        explicitly uncertain instead of admitting a second task.
        """
        assert self._a2a_delegator is not None
        task = self._a2a_delegator.get_task_by_delegation_key(key)
        if task is None:
            await self._pause_for_reconciliation(
                inputs,
                child_id,
                error="transport acceptance is uncertain; reconcile required",
            )
        await self._attach_receipt(child_id, task.id, target=task.to_agent)
        self._pause(inputs, task_id=task.id, mode="in_process", run_id=child_id)
        return DelegateRemoteOut()

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
        key = self._delegation_key(inputs, ctx)
        child = await self._existing_child(key)
        if child is None:
            try:
                target = self._a2a_delegator.resolve_target(
                    inputs.from_agent,
                    inputs.task,
                    inputs.to_agent,
                    self._mode_for(inputs),
                )
            except ValueError as exc:
                return DelegateRemoteOut(status="rejected", error=str(exc))
            child_id = await self._reserve_child(
                inputs, ctx, parent=parent, mode="in_process", target=target
            )
        else:
            child_id = child.run_id
            if await self._pause_on_existing_receipt(inputs, child, child_id, mode="in_process"):
                return DelegateRemoteOut()

        claimed = await self._claim_transport_attempt(child_id)
        if not claimed:
            return await self._recover_in_process(inputs, key, child_id)

        try:
            task_id = self._a2a_delegator.delegate_task(
                inputs.from_agent,
                inputs.task,
                inputs.to_agent,
                delegation_mode=self._mode_for(inputs),
                metadata={"delegation_key": key},
            )
        except ValueError as exc:
            await self._release_unaccepted_child(child_id)
            return DelegateRemoteOut(status="rejected", error=str(exc))

        admitted_target = self._admitted_target(task_id, inputs)
        await self._attach_receipt(child_id, task_id, target=admitted_target)
        self._pause(inputs, task_id=task_id, mode="in_process", run_id=child_id)
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

        Scope validation remains ahead of reservation and transport, so a
        delegation naming a foreign Workspace is refused before any work can
        be handed over. The guard is the same one `create_run` enforces --
        `validate_child_scope`, called from both -- rather than a copy that
        could drift into being the weaker of the two.

        Returns the parent Run so the dispatch path does not fetch it twice, or
        `None` when no store is wired.
        """
        if self._run_store is None:
            return None

        from maistro.runs.store import RunIntegrityError, validate_child_scope

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

        # A remote delegation is a child of the physical NodeRun that admitted
        # it, not merely of the containing Run. Refuse an incomplete context
        # before the A2A transport creates work we cannot correlate.
        if not ctx.node_run_id:
            raise RunIntegrityError(
                "agent.delegate_remote requires node_run_id to create a correlated child Run"
            )
        parent_node_run = await self._run_store.get_node_run(ctx.node_run_id)
        if parent_node_run is None or parent_node_run.run_id != parent.run_id:
            raise RunIntegrityError(
                f"parent_node_run_id {ctx.node_run_id!r} does not belong to parent_run_id "
                f"{parent.run_id!r}"
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

        This is the durable admission point for #1090. The child Run and its
        delegation key are committed before transport acceptance; the A2A task
        id is attached afterwards as a receipt. `ctx` carries the parent
        `run_id` and `node_run_id`, so recovery can find this exact child
        without inventing a second delegation lifecycle.

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
            parent_node_run_id=ctx.node_run_id,
            persona_id=parent.persona_id,
            actor_principal_id=parent.actor_principal_id,
            provenance={
                "admission_source": "a2a_delegation",
                # The A2A task id stays a receipt of the transport rather than
                # the work's identity, the way TaskResponse does for the queue.
                "a2a_task_id": task_id,
                "delegation_key": self._delegation_key(inputs, ctx),
                "delegation_mode": mode,
                "delegating_agent": inputs.from_agent,
                "target_agent": target,
                "peer_name": inputs.peer_name,
            },
            initial_status=RunStatus.QUEUED,
        )
        # The external transport is already the physical worker. Persist its
        # admission as a yielded Attempt instead of leaving a Run with no
        # NodeRun/Attempt or inventing a second scheduler for the child.
        from maistro.runs.reconciliation import AttemptLifecycleReconciler

        lifecycle = AttemptLifecycleReconciler(self._run_store)
        for child_node in graph.nodes:
            child_node_run = await self._run_store.create_node_run(
                child.run_id, node_id=child_node.node_id
            )
            await lifecycle.prepare_execution(child_node_run.node_run_id)
            attempt = await self._run_store.create_attempt(
                child_node_run.node_run_id,
                runtime_id="a2a",
                executor_id=f"agent.delegate_remote:{mode}",
            )
            token = attempt.execution_lease.fencing_token if attempt.execution_lease else None
            attempt = await self._run_store.transition_attempt(
                attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token
            )
            attempt = await self._run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.YIELDED,
                result={"task_id": task_id, "mode": mode},
                fencing_token=token,
            )
            await lifecycle.reconcile(attempt)
        return child.run_id

    def _child_graph(self, inputs: DelegateRemoteIn, *, parent: Run, target: str) -> Graph:
        """Snapshot the delegated request without inventing executable work.

        The A2A transports in this node accept only the text task (and the
        cross-instance transport sends only its message list). An inline
        ``subgraph`` therefore cannot be treated as work that the peer ran:
        doing so would make the child Run claim evidence for a graph that was
        never sent. Preserve the request as opaque node inputs instead; a
        transport that later supports graph payloads can add a distinct
        admission path without changing this record's meaning.
        """
        from maistro.graph.definitions import Graph, Node

        workspace_id = inputs.to_workspace_id or parent.workspace_id
        project_id = inputs.to_project_id or parent.project_id
        name = f"delegation:{inputs.from_agent or 'unknown'}->{target or 'unknown'}"

        # Resolve through the registered projection class rather than keeping
        # the class write-only; the same symbol defines the catalog kind and the
        # child snapshot's opaque node type.
        opaque_kind = AgentRemoteWorkNode.kind
        return Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            nodes=[
                Node(
                    node_type=opaque_kind,
                    name=target,
                    inputs={
                        "task": inputs.task,
                        "from_agent": inputs.from_agent,
                        "to_agent": target,
                        "peer_name": inputs.peer_name,
                        # Retain an untransmitted subgraph as request context,
                        # never as executable child topology.
                        "requested_subgraph": inputs.subgraph,
                    },
                )
            ],
        )

    def _pause(self, inputs: DelegateRemoteIn, *, task_id: str, mode: str, run_id: str) -> None:
        """Checkpoint the DAG until the delegated task completes or times out."""
        resume_at = now_utc() + timedelta(seconds=inputs.timeout_seconds)
        pause_until(
            PAUSE_AWAITING_REMOTE_DELEGATION,
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
