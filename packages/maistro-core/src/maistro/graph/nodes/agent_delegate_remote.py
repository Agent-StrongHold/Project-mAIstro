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

The cross-instance path is an *external Agent call* and is governed as such
(issue #959, M9-D2): admission binds it to the canonical caller, the
Workspace/Project scope, the delegated Goal/Subgoal context and the
dispatching Run/NodeRun/Attempt (:class:`DelegationContext`, recorded on the
delegated child Run and carried on the request), attenuates the claimed
capability scopes against the peer's declared ceiling, and crosses the
canonical Binding -> Invocation seam as one `agent_delegation` Invocation
beneath the dispatching Attempt. The remote peer's task id is a receipt;
it never replaces canonical identity.

Audit trail goes through the existing `AuditLogger` Protocol from
`guest_peers.py` (used only on the cross-instance path, since that's the
only path that already defines one) rather than a new one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NoReturn, cast

from pydantic import BaseModel, Field

from maistro.a2a.delegate import A2ADelegator, DelegationMode
from maistro.a2a.delegation_context import (
    DelegationContext,
    DelegationContextError,
    DelegationScopeExceeded,
    validate_goal_binding,
)
from maistro.a2a.guest_peers import GuestPeerManager, PeerTrust
from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.governed_invocation import (
    InvocationApprovalRequired,
    InvocationDenied,
)
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    Invocation,
    InvocationStatus,
    ReconciliationDisposition,
    UnsafeEffectRetry,
)
from maistro.capabilities.types import Unavailable
from maistro.graph.nodes.capability_effect import invoke_capability_effect
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    RunStatus,
)

from . import register_node
from .base import (
    PAUSE_AWAITING_DELEGATION_RECONCILIATION,
    PAUSE_AWAITING_REMOTE_DELEGATION,
    BaseNode,
    KindCategory,
    NodeContext,
    ReplaySemantics,
    _NodePaused,
    now_utc,
    pause_until,
    replay_effect_key,
)

if TYPE_CHECKING:
    from maistro.graph.definitions import Graph, Node
    from maistro.runs.model import NodeRun, Run
    from maistro.runs.reconciliation import AttemptLifecycleReconciler
    from maistro.runs.store import RunStore


#: The canonical capability every external Agent delegation fulfills
#: (ADR-081226-6b46: agent/A2A is a protocol family beneath
#: Capability -> Provider -> Binding -> Invocation). A cross-instance
#: dispatch is authorized by a Workspace/Project-scoped Binding of this
#: capability and is recorded as one governed Invocation.
AGENT_DELEGATION_CAPABILITY = "agent_delegation"


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


class _PeerAdmissionRefused(Exception):
    """The external dispatch was refused before any child Run or transport."""


class _PeerDelegationProvider:
    """The registered peer, viewed as the delegation capability's provider.

    Provider metadata only -- the trust tier is the operator-declared one on
    :class:`PeerTrust`, and the credential never touches this object (the
    transport reads it just in time for the one POST). It satisfies
    :class:`ResolvedCapabilityProvider` so the governed Invocation can persist
    the exact provider decision beside the effect.
    """

    def __init__(self, peer: PeerTrust) -> None:
        self.peer = peer

    @property
    def name(self) -> str:
        return self.peer.peer_name

    @property
    def slot(self) -> str:
        return AGENT_DELEGATION_CAPABILITY

    @property
    def trust_tier(self) -> str:
        return self.peer.trust_tier


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
    # External-delegation governance (issue #959): a cross-instance dispatch
    # is a governed capability effect. The Binding is the Workspace/Project
    # authorization for the external Agent call; naming an id grants nothing
    # the Binding store does not resolve.
    binding_id: str = Field(
        default="",
        description="Authorized agent_delegation Binding for a cross-instance dispatch",
    )
    # The Goal/Subgoal context this delegation advances. Absent stays absent;
    # a bound Goal names its revision (canonical Goal identity carries one).
    goal_id: str = Field(default="", description="Goal this delegation advances")
    goal_revision: int | None = Field(
        default=None, ge=1, description="Revision of the bound Goal (required with goal_id)"
    )
    subgoal_of: str = Field(default="", description="Parent Goal when the bound Goal is a subgoal")
    # The capability scopes claimed for the delegatee. Attenuated against the
    # peer's declared ceiling before dispatch; a claim beyond the ceiling is
    # refused rather than silently narrowed.
    delegated_scopes: tuple[str, ...] = Field(
        default=(), description="Capability scopes delegated to the external Agent"
    )


class DelegateRemoteOut(BaseModel):
    """Result of a delegated task once the remote session resumes or fails."""

    status: DelegationStatus = "completed"
    task_id: str = ""
    #: The canonical child Run. `task_id` stays a receipt of the A2A transport;
    #: this is the execution identity the resumed result correlates to.
    run_id: str = ""
    #: Remote Agent provenance reported back with the answer, when the peer
    #: provides it. Recorded beside the canonical identity, never instead of it.
    remote_agent_version: str = ""
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
    # Enforced, not descriptive (#1194): the work itself executes at the A2A
    # peer, so whether a failed visit already produced its effect is never
    # locally observable. Retrying here would re-dispatch the same logical
    # work the delegation contract already filed under a stable Run/NodeRun
    # identity; reconciliation of an interrupted delegation belongs to the
    # delegation recovery path (lease reclaim, guest-peer settle), never to a
    # blind second visit. ``_execute`` below refuses local replay for the
    # same reason, and the executor's retry policy honours this declaration
    # mechanically.
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.NON_RETRYABLE

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
        "effect_context": "effect_context",
    }
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = DelegateRemoteIn
    output_schema: ClassVar[type[BaseModel]] = DelegateRemoteOut
    cost_hint: ClassVar[float] = 0.0
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
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
        effect_context: CapabilityEffectContext | None = None,
    ) -> None:
        """Wire in the delegator, the guest-peer manager, the Run store and
        the canonical effect authority.

        `run_store` is what turns delegated work into a canonical child Run
        rather than an `A2ATask` with its own competing lifecycle. Optional so
        the node stays constructible in tests that only exercise dispatch, but
        `build_node_resolver` supplies it in production.

        `effect_context` is the governed Binding/Invocation authority the
        cross-instance dispatch crosses (issue #959): the external Agent call
        is one `agent_delegation` Invocation beneath the dispatching Attempt.
        Without it, the cross-instance path is a wiring fault and refuses
        rather than dispatching an unrecorded external call.
        """
        self._a2a_delegator = a2a_delegator
        self._guest_peers = guest_peers
        self._run_store = run_store
        self._effects = effect_context

    async def _execute(self, inputs: DelegateRemoteIn, ctx: NodeContext) -> DelegateRemoteOut:
        """Dispatch on first run, or return the resumed delegation result."""
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        resumed = answers.get(ctx.node_id)
        if resumed is not None:
            return await self._resume(resumed)

        if inputs.peer_name is not None:
            return await self._dispatch_cross_instance(inputs, ctx)
        return await self._dispatch_in_process(inputs, ctx)

    def _delegation_key(self, inputs: DelegateRemoteIn, ctx: NodeContext) -> str:
        """The canonical replay identity for one logical delegation.

        Bound to the executable replay contract (``replay_effect_key``) rather
        than a node-private scheme: Run + graph node scopes the logical effect,
        and the input digest distinguishes explicit new work at the same node.
        Neither the Attempt nor the NodeRun visit takes part -- a lease-loss
        retry gets new physical identities but the same durable inputs, so it
        adopts the child reservation already made instead of filing a second
        delegation. The request details remain durable on the child graph and
        provenance; they are not a second admission identity.
        """
        return replay_effect_key(ctx, self.kind, inputs.model_dump(mode="json"))

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
        context: DelegationContext | None = None,
    ) -> str:
        """Reserve once; a concurrent replica adopts the unique-key winner."""
        try:
            return await self._create_child_run(
                inputs, ctx, parent=parent, mode=mode, target=target, context=context
            )
        except Exception:
            existing = await self._existing_child(self._delegation_key(inputs, ctx))
            if existing is None:
                raise
            # Whatever is durable under this key -- the durable stores'
            # unique index hands a concurrent replica a winner that may still
            # be mid-write, and a fault in this process leaves its own
            # half-admitted child -- is adopted only once its canonical
            # evidence exists. Adopting a bare Run row is the #147 verification
            # defect: the parent paused on a child with zero NodeRuns, a shape
            # no answer could ever settle because there was nothing to attach
            # the answer's Attempt to.
            await self._ensure_child_evidence(existing.run_id)
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
            # Remote Agent provenance (issue #959), when the answering peer
            # reported it. Carried beside the canonical identity; an answer
            # without it stays without it.
            remote_agent_version=str(resumed.get("remote_agent_version") or ""),
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

        from maistro.runs.reconciliation import AttemptLifecycleReconciler

        child = await self._run_store.get_run(run_id)
        open_node_runs = await self._open_child_node_runs(run_id)
        if not open_node_runs:
            return

        # The dispatch-time provenance (peer endpoint, canonical identity
        # binding) is durable on the child; the settling Attempt's evidence
        # cites it so the answer and its provenance travel together.
        provenance = child.provenance if child is not None else {}
        peer_provenance = {
            key: provenance[key] for key in ("a2a_peer_url", "peer_name") if provenance.get(key)
        }

        lifecycle = AttemptLifecycleReconciler(self._run_store)
        cancelled_node_runs: list[str] = []
        for node_run in open_node_runs:
            if await self._record_node_run_attempt(
                node_run, out, lifecycle, peer_provenance=peer_provenance
            ):
                cancelled_node_runs.append(node_run.node_run_id)

        if cancelled_node_runs:
            await self._cancel_child(run_id, cancelled_node_runs, error=out.error)

    async def _open_child_node_runs(self, run_id: str) -> list[NodeRun]:
        """The child's NodeRuns still owing terminal evidence, or none.

        Empty when the child is gone, already terminal, or fully settled. A
        child Run with no NodeRun at all is a wiring fault, not a settled
        Run -- nothing would exist to attach the answer's Attempt to.
        """
        assert self._run_store is not None
        from maistro.runs.model import TERMINAL_RUN_STATUSES

        child = await self._run_store.get_run(run_id)
        if child is None or child.status in TERMINAL_RUN_STATUSES:
            return []
        node_runs = await self._run_store.list_node_runs(run_id)
        if not node_runs:
            raise DelegationNotConfiguredError(
                f"child Run {run_id!r} has no NodeRun for its delegated work"
            )
        return [node_run for node_run in node_runs if node_run.status not in TERMINAL_RUN_STATUSES]

    async def _record_node_run_attempt(
        self,
        node_run: NodeRun,
        out: DelegateRemoteOut,
        lifecycle: AttemptLifecycleReconciler,
        *,
        peer_provenance: dict[str, Any] | None = None,
    ) -> bool:
        """Write the response as one NodeRun's Attempt evidence.

        True when the NodeRun was cancelled: the Run may only terminalize
        after every cancelled sibling has its own evidence recorded. False
        when the outcome was accepted onto this NodeRun directly.
        """
        assert self._run_store is not None
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
            await self._run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.CANCELLED,
                error=out.error,
                fencing_token=token,
            )
            # Reconcile after all siblings are marked, otherwise the first
            # cancellation would terminalize the Run while later NodeRuns
            # still need their evidence recorded.
            return True

        # one (ADR-082526-7f02: dispatch identity belongs to the Attempt); an
        # answer without a receipt records its absence instead of a placeholder.
        # The remote endpoint/version provenance rides beside the receipt: the
        # answer cites where the work ran, so the evidence survives storage,
        # replay, and later extension/Agent version changes (issue #959).
        evidence = self._answer_evidence(out, peer_provenance)
        attempt = await self._run_store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.COMPLETED,
            result=evidence,
            error=out.error,
            fencing_token=token,
        )
        accepted = AcceptedNodeOutcome(
            node_run_id=node_run.node_run_id,
            attempt_result=AttemptResult.from_attempt(attempt),
            logical_status=(RunStatus.COMPLETED if out.status == "completed" else RunStatus.FAILED),
            result=out.result if out.status == "completed" else None,
            error=out.error,
        )
        await lifecycle.accept_outcome(accepted)
        return False

    @staticmethod
    def _answer_evidence(
        out: DelegateRemoteOut,
        peer_provenance: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """The settling Attempt's evidence: outcome, receipt, provenance."""
        evidence: dict[str, Any] = {"status": out.status, "result": out.result}
        if out.task_id:
            evidence["task_id"] = out.task_id
        if out.remote_agent_version:
            evidence["remote_agent_version"] = out.remote_agent_version
        for key, value in (peer_provenance or {}).items():
            if value:
                evidence[key] = value
        return evidence

    async def _cancel_child(
        self, run_id: str, node_run_ids: list[str], *, error: str | None
    ) -> None:
        """Terminalize cancelled sibling NodeRuns, then the child Run itself."""
        assert self._run_store is not None
        for node_run_id in node_run_ids:
            await self._run_store.transition_node_run(node_run_id, RunStatus.CANCELLED, error=error)
        await self._run_store.transition_run(run_id, RunStatus.CANCELLED, error=error)

    async def _recover_cross_instance(
        self,
        inputs: DelegateRemoteIn,
        ctx: NodeContext,
        *,
        binding: Binding,
        key: str,
        child_id: str,
    ) -> DelegateRemoteOut:
        """Reconcile a claimed boundary without submitting a second request."""
        assert self._guest_peers is not None
        assert self._run_store is not None
        current = await self._run_store.get_run(child_id)
        receipt = str(current.provenance.get("a2a_task_id") or "") if current else ""
        if receipt:
            self._pause(inputs, task_id=receipt, mode="guest_peer", run_id=child_id)
            return DelegateRemoteOut()
        # The staleness vouch is taken before the query: this visit is here
        # only because `invoke` refused the row, so no live dispatch exists in
        # this process (the service's process-local guard still enforces that
        # independently), and the receipt the peer returns is its own immutable
        # acceptance record for the delegation key -- definitive evidence, not
        # a stale guess. Without a cutoff, a worker that crashed after the peer
        # accepted (row RUNNING, dispatch_active=True) would raise
        # UnsafeEffectRetry here forever and the receipt would never attach.
        recovered_at = now_utc()
        reconciled = await self._guest_peers.reconcile(inputs.peer_name or "", key)
        if reconciled.status == "submitted" and reconciled.task_id:
            # The peer's idempotent receipt query answered: settle the
            # dispatch Invocation the first visit left unresolved, then attach
            # the receipt it names. The Invocation evidence and the child Run
            # converge on the same accepted fact.
            await self._settle_dispatch_invocation(
                ctx,
                binding,
                key,
                task_id=reconciled.task_id,
                peer_url=reconciled.peer_url,
                stale_before=recovered_at,
            )
            await self._attach_receipt(child_id, reconciled.task_id)
            self._pause(inputs, task_id=reconciled.task_id, mode="guest_peer", run_id=child_id)
            return DelegateRemoteOut()
        await self._pause_for_reconciliation(
            inputs,
            child_id,
            error=reconciled.error or "transport acceptance is uncertain; reconcile required",
        )

    async def _settle_dispatch_invocation(
        self,
        ctx: NodeContext,
        binding: Binding,
        key: str,
        *,
        task_id: str,
        peer_url: str = "",
        stale_before: datetime | None = None,
    ) -> None:
        """File recovery evidence on the dispatch Invocation, through the seam.

        The row is found by its own effect key -- the delegation key the child
        Run carries -- and settled APPLIED with the receipt as evidence. A row
        from another process's private ledger is simply absent here; the
        receipt attach remains the canonical recovery either way, so an
        unavailable or absent row is not a failure of the recovery.

        `stale_before` is the caller's vouch that the original dispatcher is
        gone (or its outcome provably captured by the receipt query): without
        it, reconciliation of a crashed RUNNING row with dispatch_active=True
        is refused as unsafe and the receipt can never settle.
        """
        if self._effects is None:
            return
        latest = await self._effects.invocations.latest_effect(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            effect_key=key,
            logical_effect=True,
        )
        if latest is None or latest.status in {
            InvocationStatus.COMPLETED,
            InvocationStatus.FAILED,
        }:
            return
        await self._effects.invocations.reconcile(
            latest.invocation_id,
            disposition=ReconciliationDisposition.APPLIED,
            source="a2a-peer-reconcile",
            actor="system:a2a",
            reason="peer idempotent receipt query reported the delegation accepted",
            evidence={"task_id": task_id, "peer_url": peer_url},
            workspace_id=latest.workspace_id or binding.workspace_id,
            project_id=latest.project_id or binding.project_id,
            result={
                "status": "submitted",
                "task_id": task_id,
                "peer_url": peer_url,
            },
            stale_before=stale_before,
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
            await self._record_child_outcome(
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
        """Delegate to a trusted external peer, then pause.

        An external Agent call is a governed capability effect (issue #959,
        ADR-081226-6b46): admission resolves the canonical identity binding,
        attenuates the claimed scopes against the peer's declared ceiling, and
        crosses the Binding -> Invocation seam before any bytes reach the
        peer. The POST itself is one `agent_delegation` Invocation beneath the
        dispatching Attempt, keyed by the same delegation key the child Run
        and the transport share.
        """
        self._require_cross_instance_wiring()
        try:
            parent, peer, context, binding = await self._admit_external_dispatch(inputs, ctx)
        except _PeerAdmissionRefused as refused:
            # Admission decides whether a *new* dispatch may start. A previous
            # visit's claimed effect is not a new dispatch: its acceptance at
            # the peer is unknown, so it is settled by the recovery paths even
            # when today's configuration (a disabled peer, a tightened scope
            # ceiling) would refuse to start one (issue #959 -- a possibly-
            # accepted remote execution stays traceable and recoverable).
            recovered = await self._recover_refused_dispatch(inputs, ctx)
            if recovered is not None:
                return recovered
            # Refused before admission with nothing claimed, so no child Run
            # is filed and no transport was touched -- the same shape as a
            # peer-side decline.
            return DelegateRemoteOut(status="rejected", error=str(refused))

        key = self._delegation_key(inputs, ctx)
        child = await self._existing_child(key)
        if child is None:
            child_id = await self._reserve_child(
                inputs,
                ctx,
                parent=parent,
                mode="guest_peer",
                target=inputs.peer_name or "",
                context=context,
            )
        else:
            child_id = child.run_id
            if await self._pause_on_existing_receipt(inputs, child, child_id, mode="guest_peer"):
                return DelegateRemoteOut()
            await self._ensure_child_evidence(child_id)

        # A previous visit may have crossed the Invocation boundary and died
        # before the pause was persisted. Its COMPLETED dispatch is the
        # accepted effect: adopt its receipt instead of dispatching again.
        replayed = await self._completed_dispatch(binding=binding, ctx=ctx, key=key)
        if replayed is not None:
            # Settle the persisted outcome exactly as the first visit would
            # have: a receipt is adopted, a declined dispatch releases the
            # reserved child, and a completed row without a receipt parks on
            # reconciliation. Re-deriving any of that here would diverge from
            # the settlement the Invocation actually records.
            return await self._settle_invoked_dispatch(inputs, replayed, child_id=child_id)

        return await self._invoke_peer_dispatch(
            inputs,
            ctx,
            binding=binding,
            peer=peer,
            context=context,
            key=key,
            child_id=child_id,
        )

    async def _recover_refused_dispatch(
        self,
        inputs: DelegateRemoteIn,
        ctx: NodeContext,
    ) -> DelegateRemoteOut | None:
        """Recover an already-claimed dispatch before a refusal stands.

        A refusal by current configuration -- peer disabled or removed, a
        tightened scope ceiling -- must not strand an effect a previous visit
        already claimed: the durable receipt pauses the delegation, and a
        claimed-but-receiptless child enters the reconciliation paths, which
        settle it from the peer's idempotent receipt query without a second
        POST. A child whose boundary was never crossed has no remote effect:
        the refusal owns it, so the reservation is released (it must not
        survive as canonical evidence implying remote work) and ``None`` is
        returned for the caller's honest rejection.

        The governing Binding is re-resolved on the parent's scope for the
        Invocation settle; a binding removed since the claim surfaces as a
        node failure rather than a silent skip, and the claimed child stays
        in place for the operator instead of being discarded.
        """
        assert self._run_store is not None
        key = self._delegation_key(inputs, ctx)
        child = await self._existing_child(key)
        if child is None:
            return None
        if await self._pause_on_existing_receipt(inputs, child, child.run_id, mode="guest_peer"):
            return DelegateRemoteOut()
        if not child.provenance.get("transport_attempted"):
            # No transport was ever attempted, so nothing remote can exist:
            # the refusal is this instance's own, and the reservation must
            # not survive as a canonical Run implying remote work -- the same
            # rule the governed refusals below the seam obey.
            await self._release_unaccepted_child(child.run_id)
            return None
        parent = await self._preflight_child_scope(inputs, ctx)
        assert self._effects is not None
        assert parent is not None, "the child's reservation recorded a parent scope"
        binding = await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=parent.workspace_id,
            project_id=parent.project_id,
            node_id=ctx.node_id,
            capability=AGENT_DELEGATION_CAPABILITY,
        )
        return await self._recover_cross_instance(
            inputs, ctx, binding=binding, key=key, child_id=child.run_id
        )

    def _require_cross_instance_wiring(self) -> None:
        """Refuse the external path when this instance cannot govern it.

        Both are wiring faults of this instance, not refusals by the remote
        peer: an unwired manager cannot even name a target, and a missing
        effect authority would mean dispatching an external Agent call no
        Invocation records (issue #959). The node fails loudly instead.
        """
        if self._guest_peers is None:
            raise DelegationNotConfiguredError(
                "agent.delegate_remote reached a cross-instance dispatch with no "
                "guest_peers manager. This is a wiring fault in this instance, not "
                "a refusal by the remote peer -- see build_node_resolver (#147)."
            )
        if self._effects is None:
            raise DelegationNotConfiguredError(
                "agent.delegate_remote reached a cross-instance dispatch with no "
                "effect_context. An external Agent call is a governed Invocation; "
                "dispatching one without the canonical effect authority would "
                "create an unrecorded external call -- see build_node_resolver."
            )

    async def _admit_external_dispatch(
        self, inputs: DelegateRemoteIn, ctx: NodeContext
    ) -> tuple[Run, PeerTrust, DelegationContext, Binding]:
        """Resolve everything admission owes before any reservation or POST.

        The Binding is the Workspace/Project authorization for the external
        call; the peer's trust record supplies the authority ceiling the
        claimed scopes are attenuated against. A peer this instance does not
        trust, or a scope claim beyond the ceiling, refuses here -- before a
        child Run exists, so a rejection never files an execution.
        """
        if not inputs.binding_id.strip():
            raise BindingNotFound(
                "agent.delegate_remote requires a pre-authorized binding_id "
                "before an external Agent dispatch"
            )
        parent = await self._preflight_child_scope(inputs, ctx)
        peer = self._guest_peers.get_peer(inputs.peer_name or "") if self._guest_peers else None
        if peer is None:
            raise _PeerAdmissionRefused("peer not found")
        if not peer.active:
            raise _PeerAdmissionRefused("peer inactive")
        context = self._canonical_context(inputs, ctx, parent=parent, peer=peer)
        assert self._effects is not None, "wiring checked before admission"
        assert parent is not None, "_canonical_context refuses a parentless dispatch"
        binding = await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            node_id=ctx.node_id,
            capability=AGENT_DELEGATION_CAPABILITY,
        )
        return parent, peer, context, binding

    def _canonical_context(
        self,
        inputs: DelegateRemoteIn,
        ctx: NodeContext,
        *,
        parent: Run | None,
        peer: PeerTrust,
    ) -> DelegationContext:
        """Bind the dispatch to the canonical caller, scope and execution.

        The canonical caller is the parent Run's actor principal -- the same
        identity the Run model already requires -- and the Workspace/Project
        scope is the parent's, which `_preflight_child_scope` has already
        settled. No external Agent call is admitted without both, so a
        store-less construction (which cannot know them) is refused here
        rather than dispatched with an invented identity.

        The claimed scopes are attenuated against the peer's declared ceiling;
        an excess claim is a policy refusal filed before any child Run exists.
        """
        if parent is None or not ctx.node_run_id:
            raise DelegationContextError(
                "an external Agent delegation requires the delegating Run's canonical "
                "caller and scope; dispatch without a correlated parent NodeRun is refused"
            )
        try:
            context = DelegationContext(
                # The Run model already requires a non-empty actor principal;
                # a context without one is refused here by the field itself.
                caller_principal_id=str(parent.actor_principal_id or ""),
                delegating_agent=inputs.from_agent.strip(),
                workspace_id=parent.workspace_id,
                project_id=parent.project_id,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                goal_id=inputs.goal_id.strip(),
                goal_revision=inputs.goal_revision,
                subgoal_of=inputs.subgoal_of.strip(),
                delegated_scopes=tuple(inputs.delegated_scopes),
                delegation_key=self._delegation_key(inputs, ctx),
            )
            validate_goal_binding(context)
        except ValueError as exc:
            raise DelegationContextError(
                f"external Agent delegation lacks its canonical identity binding: {exc}"
            ) from exc
        try:
            return context.narrowed(peer.allowed_scopes)
        except DelegationScopeExceeded as exc:
            # A scope claim beyond the peer's declared ceiling is a policy
            # refusal the Graph may branch on, filed before any child Run
            # exists and before any transport was touched.
            raise _PeerAdmissionRefused(str(exc)) from exc

    def _in_process_context(
        self,
        inputs: DelegateRemoteIn,
        ctx: NodeContext,
        *,
        parent: Run | None,
    ) -> DelegationContext | None:
        """The identity binding for an in-process delegation, or None.

        Same record as the external path minus the transport fields that do
        not apply: no peer ceiling attenuates it (the delegator's own
        allow-lists govern in-process targets) and no Attempt is claimed yet.
        None keeps store-less test constructions working -- those have no
        canonical caller to name, and they dispatch nothing external.
        """
        if parent is None or not ctx.node_run_id:
            return None
        try:
            context = DelegationContext(
                caller_principal_id=str(parent.actor_principal_id or ""),
                delegating_agent=inputs.from_agent.strip(),
                workspace_id=parent.workspace_id,
                project_id=parent.project_id,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                goal_id=inputs.goal_id.strip(),
                goal_revision=inputs.goal_revision,
                subgoal_of=inputs.subgoal_of.strip(),
                delegated_scopes=tuple(inputs.delegated_scopes),
                delegation_key=self._delegation_key(inputs, ctx),
            )
            validate_goal_binding(context)
        except ValueError:
            # An in-process delegation with a malformed Goal binding still
            # dispatches (the delegator's allow-lists govern it); the binding
            # simply stays unrecorded rather than lying about the Goal.
            return None
        return context

    async def _completed_dispatch(
        self, *, binding: Binding, ctx: NodeContext, key: str
    ) -> Invocation | None:
        """A dispatch Invocation this Run already completed, or None.

        A lease-loss retry derives the same delegation key, so the canonical
        row the first visit recorded replays here instead of the transport
        being asked a second time. Scoped to this Run, exactly as the effect
        service scopes its own replays.
        """
        latest = await self._effects.invocations.latest_effect(  # type: ignore[union-attr]
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            effect_key=key,
            logical_effect=True,
        )
        if latest is None or latest.status is not InvocationStatus.COMPLETED:
            return None
        # COMPLETED is terminal evidence whatever the outcome: a decline is a
        # completed call with `status: "rejected"` and intentionally no task
        # ID. Filtering on the receipt here would bury the recorded outcome
        # and send the retry polling for a receipt that can never exist.
        return latest

    async def _invoke_peer_dispatch(
        self,
        inputs: DelegateRemoteIn,
        ctx: NodeContext,
        *,
        binding: Binding,
        peer: PeerTrust,
        context: DelegationContext,
        key: str,
        child_id: str,
    ) -> DelegateRemoteOut:
        """Cross the governed Invocation boundary, then settle the dispatch.

        The executor performs the physical POST through `GuestPeerManager`;
        everything around it -- policy, admission, effect identity, the
        persisted row with its Workspace/Run/NodeRun/Attempt correlation --
        belongs to the canonical Invocation service. Transport failure keeps
        the reserved child and parks on reconciliation: the peer's acceptance
        is unknown, so no outcome here may read as completed.
        """
        assert self._guest_peers is not None
        assert self._effects is not None
        request_payload = {
            "peer_name": peer.peer_name,
            "agent_id": context.delegating_agent,
            "task": inputs.task,
            "idempotency_key": key,
            "delegation_context": context.as_payload(),
        }

        async def resolve_provider(
            authorized: Binding,
        ) -> ResolvedCapabilityProvider | Unavailable:
            if authorized.provider_name and authorized.provider_name != peer.peer_name:
                return Unavailable(
                    slot=AGENT_DELEGATION_CAPABILITY,
                    reason=(
                        f"Binding pins provider {authorized.provider_name!r}, not "
                        f"requested peer {peer.peer_name!r}"
                    ),
                )
            return _PeerDelegationProvider(peer)

        async def execute_provider(provider: ResolvedCapabilityProvider, request: Any) -> Any:
            # The transport boundary is claimed here -- inside the governed
            # executor, after admission and policy have passed -- not at
            # reservation. An approval pause must not leave a child marked
            # `transport_attempted` for a POST that never happened: the
            # post-approval visit re-enters with the claim still free and
            # executes, instead of reconciling a dispatch that never started.
            claimed = await self._claim_transport_attempt(child_id)
            if not claimed:
                # Another replica won the boundary while this visit sat in
                # policy or approval. The peer's idempotent receipt query,
                # never a second POST, settles whose dispatch is canonical.
                raise UnsafeEffectRetry(
                    f"delegation transport for effect {key!r} was claimed by another visit"
                )
            return await self._execute_peer_delegation(
                provider,
                request,
                context=context,
                key=key,
                messages=[{"role": "user", "content": inputs.task}],
            )

        try:
            invocation = await invoke_capability_effect(
                lambda: self._effects.invocations.invoke(  # type: ignore[union-attr]
                    binding=binding,
                    run_id=ctx.run_id,
                    node_run_id=ctx.node_run_id,
                    attempt_id=ctx.attempt_id,
                    effect_key=key,
                    request=request_payload,
                    resolver=resolve_provider,
                    executor=execute_provider,
                    actor_id=context.caller_principal_id,
                    logical_effect=True,
                ),
                effect_key=key,
            )
        except _NodePaused:
            # A pause the governed seam itself translated -- a durable human
            # approval decision, most likely -- is the runtime's own control
            # flow. Let it surface; converting it into a reconciliation park
            # would silently swap one waiting state for another.
            raise
        except InvocationApprovalRequired:
            # An approval surface that cannot manage the decision (no store
            # wired) is a composition fault of this instance: fail the node
            # rather than parking delegated work on a recovery loop that can
            # never answer it. A *manageable* pending approval never reaches
            # this handler -- the HITL adapter converts it to a pause above.
            raise
        except (CapabilityUnavailable, InvocationDenied):
            # Nothing was dispatched: the provider is missing or policy said
            # no before the executor ran, so the transport claim is still
            # unspent. That is a refusal this instance owns, so the node
            # fails loudly instead of parking work that never crossed the
            # boundary. The reservation happened before the seam could
            # answer, so release the child: it must not survive as a
            # canonical Run implying remote work, and a retry re-reserves and
            # claims fresh rather than reconciling a dispatch that provably
            # never started.
            await self._release_unaccepted_child(child_id)
            raise
        except UnsafeEffectRetry:
            # The ledger holds an unresolved dispatch for this exact logical
            # effect. Recover it through the peer's idempotent receipt query;
            # re-POSTing is the one thing the rules forbid.
            return await self._recover_cross_instance(
                inputs, ctx, binding=binding, key=key, child_id=child_id
            )
        except Exception as exc:
            await self._pause_for_reconciliation(
                inputs,
                child_id,
                error=str(exc) or "external delegation transport is uncertain",
            )

        return await self._settle_invoked_dispatch(inputs, invocation, child_id=child_id)

    async def _settle_invoked_dispatch(
        self,
        inputs: DelegateRemoteIn,
        invocation: Invocation,
        *,
        child_id: str,
    ) -> DelegateRemoteOut:
        """Turn one completed dispatch Invocation into the node's outcome."""
        result = invocation.result if isinstance(invocation.result, dict) else {}
        if str(result.get("status") or "") == "rejected":
            await self._release_unaccepted_child(child_id)
            # No child Run: nothing was admitted, so there is no execution to
            # give an identity to. The peer declining is a legitimate outcome
            # the Graph may branch on, unlike the misconfiguration above.
            return DelegateRemoteOut(
                status="rejected",
                task_id=str(result.get("task_id") or ""),
                error=result.get("error"),
            )
        task_id = str(result.get("task_id") or "")
        if not task_id:
            await self._pause_for_reconciliation(
                inputs,
                child_id,
                error="peer accepted work without a transport receipt",
            )
        await self._attach_receipt(child_id, task_id)
        self._pause(inputs, task_id=task_id, mode="guest_peer", run_id=child_id)
        return DelegateRemoteOut()  # unreachable

    async def _execute_peer_delegation(
        self,
        provider: ResolvedCapabilityProvider,
        request: Any,
        *,
        context: DelegationContext,
        key: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        """The one physical POST, translated into Invocation result evidence.

        A transport refusal is a completed call with a declined outcome. A
        transport failure raises: the peer's acceptance is unknown, so the
        Invocation must land UNKNOWN -- the state that forces reconciliation
        -- never COMPLETED with a guessed outcome.
        """
        assert self._guest_peers is not None
        if not isinstance(provider, _PeerDelegationProvider):
            raise TypeError("delegation Invocation resolved a non-peer provider")
        result = await self._guest_peers.delegate(
            provider.peer.peer_name,
            str(request["agent_id"]),
            messages,
            idempotency_key=key,
            context=context,
        )
        if result.status == "rejected":
            return {"status": "rejected", "task_id": "", "error": result.error}
        if result.status != "submitted" or not result.task_id:
            raise RuntimeError(
                result.error or "peer delegation transport failed; acceptance unknown"
            )
        return {
            "status": "submitted",
            "task_id": result.task_id,
            "peer_url": result.peer_url,
            "agent_version": result.agent_version,
            "protocol_version": result.protocol_version,
        }

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
        # In-process delegation is not an external call, so it needs no
        # Binding/Invocation seam -- the child Run is the admission. It still
        # carries the canonical identity/Goal binding on its provenance when
        # the delegating Run is known (issue #959), so both delegation paths
        # leave the same traceability record.
        context = self._in_process_context(inputs, ctx, parent=parent)
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
                inputs, ctx, parent=parent, mode="in_process", target=target, context=context
            )
        else:
            child_id = child.run_id
            if await self._pause_on_existing_receipt(inputs, child, child_id, mode="in_process"):
                return DelegateRemoteOut()
            await self._ensure_child_evidence(child_id)

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
        mode: str,
        target: str,
        context: DelegationContext | None = None,
    ) -> str:
        """File the delegated work as a child Run of the delegating NodeRun.

        This is the durable admission point for #1090. The child Run and its
        delegation key are committed before transport acceptance; the A2A task
        id is attached afterwards as a receipt. `ctx` carries the parent
        `run_id` and `node_run_id`, so recovery can find this exact child
        without inventing a second delegation lifecycle.

        The reservation carries no receipt key at all rather than an empty one:
        at this moment no transport has accepted anything, and a placeholder
        `a2a_task_id: ""` would be exactly the lie-shaped record
        ADR-082526-7f02's AC-3 refuses ("an absent fact stays absent"). The
        receipt lands once, after acceptance, via `attach_delegation_receipt` --
        on the Run's provenance because #147's acceptance names it there, and on
        the settling Attempt's evidence, which is where the same ADR puts
        dispatch identity.

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

        from maistro.runs.store import RunIntegrityError

        # A remote delegation is a child of the physical NodeRun that admitted
        # it, not merely of the containing Run. Refuse an incomplete context
        # before the A2A transport creates work we cannot correlate. The check
        # guards creation only: a replay adopting an existing reservation under
        # the same delegation key reconciles the durable child instead of
        # re-deriving parentage from the retry's fresh physical identities
        # (#1194 -- a lease-loss retry carries a new NodeRun that the store
        # may not have made visible yet, and the replay must still adopt).
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

        graph = self._child_graph(inputs, parent=parent, target=target)
        child = await self._run_store.create_run(
            graph,
            parent_run_id=ctx.run_id,
            parent_node_run_id=ctx.node_run_id,
            persona_id=parent.persona_id,
            actor_principal_id=parent.actor_principal_id,
            provenance={
                "admission_source": "a2a_delegation",
                # The A2A task id is *not* written here: no transport has run
                # yet, so there is no receipt to record. It is attached once,
                # after acceptance, by `_attach_receipt` -- a receipt of the
                # transport rather than the work's identity, the way
                # TaskResponse does for the queue.
                # One canonical replay identity, recorded under both store
                # lookups: `delegation_key` for the transport reservation and
                # `effect_key` for the executor's effect reconciliation.
                "delegation_key": self._delegation_key(inputs, ctx),
                "effect_key": self._delegation_key(inputs, ctx),
                "delegation_mode": mode,
                "delegating_agent": inputs.from_agent,
                "target_agent": target,
                "peer_name": inputs.peer_name,
                # The canonical identity/Goal binding (issue #959): recorded
                # beside the key, so the delegated work is traceable to the
                # caller, the Workspace scope, and the Goal/Subgoal it
                # advances without re-deriving any of it from the transport.
                **({"delegation_context": context.as_payload()} if context is not None else {}),
                # Remote endpoint provenance known before dispatch: which
                # registered peer endpoint the work was pointed at. The
                # receipt and any remote Agent version land later, where the
                # transport that produced them can vouch for them.
                **(
                    {"a2a_peer_url": peer_url}
                    if (peer_url := self._registered_peer_url(inputs.peer_name))
                    else {}
                ),
            },
            # CREATED, never QUEUED. The evidence writes below are what move
            # the child through RUNNING and park it WAITING; admitting the row
            # in QUEUED instead left a window where a Run was durable in the
            # one state consumers read as "admitted work waiting to execute"
            # while carrying no NodeRun and no Attempt (#147 verification). It
            # was unrecoverable precisely because a2a_delegation is not a
            # consumable source and must never be -- the child is a projection
            # of work executing at a peer, not work this instance executes
            # (ADR-082426-6201). CREATED is the recovery model's own resting
            # state for such projections, and `_ensure_child_evidence` finishes
            # one on the next visit through this node.
            initial_status=RunStatus.CREATED,
        )
        await self._write_child_evidence(child.run_id, graph.nodes, mode=mode)
        return child.run_id

    def _registered_peer_url(self, peer_name: str | None) -> str:
        """The endpoint a registered peer names, or nothing when it is not one."""
        if not peer_name or self._guest_peers is None:
            return ""
        peer = self._guest_peers.get_peer(peer_name)
        return peer.peer_url if peer is not None else ""

    async def _write_child_evidence(self, run_id: str, nodes: Sequence[Node], *, mode: str) -> None:
        """Give the child its NodeRuns and their yielded transport Attempts.

        The external transport is already the physical worker. Persisting its
        admission as a yielded Attempt is what keeps the universal
        Run -> NodeRun -> Attempt hierarchy intact without inventing a second
        scheduler for the child; until this returns, the child is a reserved
        projection, not yet evidence-bearing work. The yielded evidence names
        the mode and nothing else -- the transport receipt does not exist yet,
        and when it does it is recorded where ADR-082526-7f02 puts dispatch
        identity: on the Attempt that settles the work.
        """
        assert self._run_store is not None
        from maistro.runs.reconciliation import AttemptLifecycleReconciler

        lifecycle = AttemptLifecycleReconciler(self._run_store)
        for child_node in nodes:
            child_node_run = await self._run_store.create_node_run(
                run_id, node_id=child_node.node_id
            )
            await self._yield_transport_attempt(child_node_run.node_run_id, lifecycle, mode=mode)

    async def _ensure_child_evidence(self, run_id: str) -> None:
        """Complete an interrupted reservation, idempotently.

        Reservation is two durable stages -- the child Run, then its
        NodeRun/Attempt evidence -- and a process can die between them, on this
        replica or on a concurrent one that lost the unique-key race mid-write.
        Resting is not finished: a resume against an evidence-less child has no
        NodeRun to attach an answer's Attempt to. This finishes whatever any
        interrupted reservation started: every graph node gets its NodeRun, and
        every NodeRun its yielded transport Attempt. A no-op on a complete
        child, and on a terminal one, which owes nothing.

        Two writers racing here converge rather than split the work: the
        durable stores hold one *active* Attempt per NodeRun and `YIELDED` is
        terminal, so the slower writer's evidence lands beside the faster's
        under the same logical NodeRun instead of forking it.
        """
        if self._run_store is None or not run_id:
            return
        child = await self._run_store.get_run(run_id)
        if child is None or child.status in TERMINAL_RUN_STATUSES:
            return
        mode = str(child.provenance.get("delegation_mode") or "in_process")
        from maistro.runs.reconciliation import AttemptLifecycleReconciler

        lifecycle = AttemptLifecycleReconciler(self._run_store)
        observed: set[str] = set()
        for node_run in await self._run_store.list_node_runs(run_id):
            observed.add(node_run.node_id)
            if not await self._has_terminal_attempt(node_run.node_run_id):
                await self._yield_transport_attempt(node_run.node_run_id, lifecycle, mode=mode)
        for child_node in child.graph.materialize().nodes:
            if child_node.node_id in observed:
                continue
            node_run = await self._run_store.create_node_run(run_id, node_id=child_node.node_id)
            await self._yield_transport_attempt(node_run.node_run_id, lifecycle, mode=mode)

    async def _has_terminal_attempt(self, node_run_id: str) -> bool:
        assert self._run_store is not None
        attempts = await self._run_store.list_attempts(node_run_id)
        return any(attempt.status in TERMINAL_ATTEMPT_STATUSES for attempt in attempts)

    async def _yield_transport_attempt(
        self,
        node_run_id: str,
        lifecycle: AttemptLifecycleReconciler,
        *,
        mode: str,
    ) -> None:
        """Record the transport's one yielded physical Attempt under a NodeRun.

        The evidence names the delegation mode and nothing else. At reservation
        time no transport has accepted anything, so there is no receipt to
        record -- and a placeholder `task_id: ""` is exactly the lie-shaped
        record ADR-082526-7f02's AC-3 refuses ("an absent fact stays absent").
        When the receipt arrives it is recorded on the Run's provenance and on
        the settling Attempt's evidence, where the same ADR puts dispatch
        identity; yielded Attempts are terminal evidence and are never amended.
        """
        assert self._run_store is not None
        await lifecycle.prepare_execution(node_run_id)
        attempt = await self._run_store.create_attempt(
            node_run_id,
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
            result={"mode": mode},
            fencing_token=token,
        )
        await lifecycle.reconcile(attempt)

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
