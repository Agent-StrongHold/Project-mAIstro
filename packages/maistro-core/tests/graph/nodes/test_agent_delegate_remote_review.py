"""The child Run has a lifecycle, an identity and a scope check that fire in
the right order (#147, review round 2).

The first pass filed a canonical child Run and stopped there. Review found the
child was created and then abandoned: persisted `created`, never transitioned,
while the parent graph moved on with the delegate's answer. The rest of these
follow from the same gap — the node knew about the child at dispatch and forgot
it at resume.

Each case here is one of those, and each fails on the code as it was.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest

from maistro.a2a.delegate import A2ADelegator
from maistro.a2a.guest_peers import GuestPeerManager, PeerTrust
from maistro.graph import Graph, Node
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes import agent_delegate_remote as delegate_module
from maistro.graph.nodes.agent_delegate_remote import AgentDelegateRemoteNode
from maistro.http import set_test_transport
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore, RunIntegrityError, RunStatus


async def _spine(*, workspace_id: str = "workspace-1") -> tuple[InMemoryRunStore, Any]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root(workspace_id)
    project = await project_store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Project"
    )
    return InMemoryRunStore(project_store=project_store), project


def _graph(*, workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="Delegating pipeline",
        nodes=[Node(node_id="delegate-1", node_type="agent.delegate_remote")],
    )


def _ctx(*, run_id: str, node_run_id: str = "", answer: dict[str, Any] | None = None):
    return NodeContext(
        run_id=run_id,
        dag_id="dag-1",
        node_id="delegate-1",
        node_run_id=node_run_id,
        metadata={"hitl_answers": {"delegate-1": answer}} if answer is not None else {},
    )


def _delegator() -> A2ADelegator:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["researcher"])
    return delegator


class _ReceiptFailingStore(InMemoryRunStore):
    """Inject the crash window between transport acceptance and receipt attach."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_receipt_once = True

    async def attach_delegation_receipt(self, run_id: str, task_id: str, *, target_agent=None):
        if self.fail_receipt_once:
            self.fail_receipt_once = False
            raise RuntimeError("injected receipt persistence failure")
        return await super().attach_delegation_receipt(run_id, task_id, target_agent=target_agent)


class _RecordingDelegator(A2ADelegator):
    """A delegator that remembers whether it was ever asked to admit work.

    The property under test is "nothing was dispatched", and `A2ADelegator`
    exposes no way to list its queue — only `get_task_status(task_id)`, which
    needs the id a refused delegation never produced. Counting the calls states
    the property directly instead of inferring it from an absence.
    """

    def __init__(self) -> None:
        super().__init__()
        self.dispatched: list[tuple[str, str, str | None]] = []

    def delegate_task(self, from_agent, task, to_agent, *args: Any, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        self.dispatched.append((from_agent, task, to_agent))
        return super().delegate_task(from_agent, task, to_agent, *args, **kwargs)


class _FailingDelegator(_RecordingDelegator):
    """Fail after the durable boundary claim, before accepting a local task."""

    def delegate_task(self, from_agent, task, to_agent, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.dispatched.append((from_agent, task, to_agent))
        raise RuntimeError("injected transport failure before acceptance")


class _ReservationFailingStore(InMemoryRunStore):
    """Inject a database failure while reserving a child Run."""

    async def create_run(self, graph, *, parent_run_id=None, **kwargs: Any):  # type: ignore[no-untyped-def]
        if parent_run_id is not None:
            raise RuntimeError("injected child admission failure")
        return await super().create_run(graph, parent_run_id=parent_run_id, **kwargs)


class _ClaimFailingNode(AgentDelegateRemoteNode):
    """Stop after child admission but before the transport claim is written."""

    async def _claim_transport_attempt(self, run_id: str) -> bool:
        raise RuntimeError("injected failure after child reservation")


def _recording_delegator() -> _RecordingDelegator:
    delegator = _RecordingDelegator()
    delegator.register_agent_capability("planner", ["researcher"])
    return delegator


async def _dispatched(store: InMemoryRunStore, project_id: str, **inputs: Any):
    """Dispatch one delegation and return `(node, parent, child_run_id)`."""
    parent = await store.create_run(_graph(workspace_id="workspace-1", project_id=project_id))
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
    node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
    result = await node.run(
        {"from_agent": "planner", "task": "research X", "to_agent": "researcher", **inputs},
        _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id),
    )
    return node, parent, str(result.metadata["run_id"])


# --------------------------------------------------------------------------
# The child Run reaches a terminal state
# --------------------------------------------------------------------------


class TestTheChildRunIsSettled:
    """Before this, `create_run` was the child's whole life.

    Neither A2A transport touches the Run store, so a completed, failed or
    timed-out answer advanced the parent graph while the canonical child still
    reported `created` with no result and no error — the same "second lifecycle
    beside the Run" this node exists to remove, one level down.
    """

    @pytest.mark.parametrize(
        ("answered", "expected"),
        [
            ("completed", RunStatus.COMPLETED),
            ("failed", RunStatus.FAILED),
            ("timed_out", RunStatus.TIMED_OUT),
            # Admitted and then declined: `cancelled` rather than `failed`,
            # which would read as attempted-and-gone-wrong.
            ("rejected", RunStatus.CANCELLED),
        ],
    )
    async def test_the_answer_settles_the_child(self, answered: str, expected: RunStatus) -> None:
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)
        assert (await store.get_run(child_run_id)).status is RunStatus.CREATED

        await node.run(
            {"from_agent": "planner", "task": "research X"},
            _ctx(
                run_id=parent.run_id,
                answer={"status": answered, "_pause": {"run_id": child_run_id}},
            ),
        )

        child = await store.get_run(child_run_id)
        assert child is not None
        assert child.status is expected
        assert child.finished_at is not None

    async def test_the_delegates_result_lands_on_the_child(self) -> None:
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)

        await node.run(
            {"from_agent": "planner", "task": "research X"},
            _ctx(
                run_id=parent.run_id,
                answer={
                    "status": "completed",
                    "result": "X is documented",
                    "_pause": {"run_id": child_run_id},
                },
            ),
        )

        child = await store.get_run(child_run_id)
        assert child is not None
        assert child.result == "X is documented"

    async def test_an_unrecognised_status_fails_loudly_instead_of_crashing(self) -> None:
        """The status also selects the child's terminal state, so a value
        outside the four would `KeyError` in the middle of settling a Run.
        Reporting it as failed *with the reason* keeps a malformed answer from
        reading as a legitimate refusal."""
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)

        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(
                run_id=parent.run_id,
                answer={"status": "banana", "_pause": {"run_id": child_run_id}},
            ),
        )

        assert result.status == "completed", "a bad answer is a delegation outcome, not a crash"
        assert result.output.status == "failed"
        assert "banana" in (result.output.error or "")
        assert (await store.get_run(child_run_id)).status is RunStatus.FAILED

    async def test_a_second_resume_does_not_reopen_a_settled_child(self) -> None:
        """A terminal Run has no outgoing transitions, so a duplicate answer
        would raise and sink a delegation whose result is already in hand."""
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)
        ctx = _ctx(
            run_id=parent.run_id,
            answer={"status": "completed", "_pause": {"run_id": child_run_id}},
        )
        await node.run({"from_agent": "planner", "task": "x"}, ctx)

        result = await node.run({"from_agent": "planner", "task": "x"}, ctx)

        assert result.status == "completed"
        assert (await store.get_run(child_run_id)).status is RunStatus.COMPLETED


# --------------------------------------------------------------------------
# The Run id survives the resume, and comes from the server
# --------------------------------------------------------------------------


class TestTheRunIdIsNotSourcedFromTheResponder:
    async def test_the_pause_payload_supplies_the_run_id(self) -> None:
        """The store deletes the node's pause entry when it attaches the answer,
        so without the stamped copy the new `run_id` output was always `""` on
        the normal resume path — a field that could never be populated."""
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)

        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(
                run_id=parent.run_id,
                answer={"status": "completed", "_pause": {"run_id": child_run_id}},
            ),
        )

        assert result.output.run_id == child_run_id

    async def test_a_responder_cannot_name_the_run_it_answers_for(self) -> None:
        """Otherwise any caller could redirect a delegation's outcome onto
        someone else's Run — the responder is the party being waited on, and
        execution identity must not come from it."""
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)
        victim = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )

        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(
                run_id=parent.run_id,
                answer={
                    "status": "failed",
                    "run_id": victim.run_id,
                    "_pause": {"run_id": child_run_id},
                },
            ),
        )

        assert result.output.run_id == child_run_id
        assert (await store.get_run(victim.run_id)).status is RunStatus.CREATED, (
            "the submitted run_id must not reach the store at all"
        )
        assert (await store.get_run(child_run_id)).status is RunStatus.FAILED


# --------------------------------------------------------------------------
# Scope is settled before anything is dispatched
# --------------------------------------------------------------------------


class TestAdmissionAndTransportConverge:
    async def test_receipt_attach_failure_retries_same_child_and_same_task(self) -> None:
        """A crash after acceptance must not create a second logical task."""
        project_store = InMemoryProjectScopeStore()
        root = await project_store.create_root("workspace-1")
        project = await project_store.create(
            workspace_id="workspace-1", parent_project_id=root.project_id, name="Project"
        )
        store = _ReceiptFailingStore(project_store=project_store)
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)
        inputs = {"from_agent": "planner", "task": "x", "to_agent": "researcher"}
        ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)

        first = await node.run(inputs, ctx)
        assert first.status == "failed"
        assert len(delegator._tasks) == 1  # transport accepted exactly once
        child = await store.find_delegation_run(
            node._delegation_key(  # type: ignore[attr-defined]
                node.input_schema.model_validate(inputs), ctx
            )
        )
        assert child is not None
        assert child.provenance.get("a2a_task_id") in (None, "")

        second = await node.run(
            {**inputs, "task": "changed after retry", "to_agent": "different-target"}, ctx
        )
        assert second.status == "paused"
        assert len(delegator._tasks) == 1
        assert (await store.get_run(second.metadata["run_id"])).provenance["a2a_task_id"]

    async def test_pause_persistence_failure_reuses_attached_receipt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)
        inputs = {"from_agent": "planner", "task": "x", "to_agent": "researcher"}
        ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)
        original_pause = delegate_module.pause_until

        def fail_pause(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("injected parent pause persistence failure")

        monkeypatch.setattr(delegate_module, "pause_until", fail_pause)
        first = await node.run(inputs, ctx)
        assert first.status == "failed"
        monkeypatch.setattr(delegate_module, "pause_until", original_pause)

        second = await node.run(inputs, ctx)
        assert second.status == "paused"
        assert len(delegator._tasks) == 1

    async def test_admission_failure_happens_before_any_local_dispatch(self) -> None:
        project_store = InMemoryProjectScopeStore()
        root = await project_store.create_root("workspace-1")
        project = await project_store.create(
            workspace_id="workspace-1", parent_project_id=root.project_id, name="Project"
        )
        store = _ReservationFailingStore(project_store=project_store)
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)

        result = await node.run(
            {"from_agent": "planner", "task": "x", "to_agent": "researcher"},
            _ctx(run_id=parent.run_id),
        )

        assert result.status == "failed"
        assert delegator.dispatched == []

    async def test_restart_after_child_reservation_can_claim_and_dispatch_once(self) -> None:
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        first_delegator = _recording_delegator()
        inputs = {"from_agent": "planner", "task": "x", "to_agent": "researcher"}
        ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)

        first = await _ClaimFailingNode(a2a_delegator=first_delegator, run_store=store).run(
            inputs, ctx
        )
        assert first.status == "failed"
        assert first_delegator.dispatched == []

        second_delegator = _recording_delegator()
        second_node = AgentDelegateRemoteNode(a2a_delegator=second_delegator, run_store=store)
        second = await second_node.run(inputs, ctx)

        assert second.status == "paused"
        assert len(second_delegator._tasks) == 1
        key = second_node._delegation_key(second_node.input_schema.model_validate(inputs), ctx)
        child = await store.find_delegation_run(key)
        assert child is not None
        task = second_delegator.get_task_by_delegation_key(key)
        assert task is not None
        assert child.provenance["a2a_task_id"] == task.id

    async def test_restart_after_boundary_claim_parks_for_reconciliation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cross-replica shape of a lost receipt: the first worker claimed
        the boundary and died before the task became visible; the retry lands
        where the task map is empty. The retry must not submit a second task
        *and* must not complete: an `uncertain` output is wrapped as a
        completed Attempt and the frontier advances, leaving the reserved child
        `created` forever. It parks on the timer-resumable reconciliation
        pause, which re-enters the node to look for the receipt again."""
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        first_delegator = _FailingDelegator()
        first_delegator.register_agent_capability("planner", ["researcher"])
        inputs = {"from_agent": "planner", "task": "x", "to_agent": "researcher"}
        ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)

        first = await AgentDelegateRemoteNode(a2a_delegator=first_delegator, run_store=store).run(
            inputs, ctx
        )
        assert first.status == "failed"

        second_delegator = _recording_delegator()
        second = await AgentDelegateRemoteNode(a2a_delegator=second_delegator, run_store=store).run(
            inputs, ctx
        )

        assert second.status == "paused"
        assert second.metadata["paused_reason"] == "awaiting_delegation_reconciliation"
        assert second_delegator.dispatched == []
        key = AgentDelegateRemoteNode(
            a2a_delegator=second_delegator, run_store=store
        )._delegation_key(AgentDelegateRemoteNode.input_schema.model_validate(inputs), ctx)
        child = await store.find_delegation_run(key)
        assert child is not None
        assert child.provenance["transport_attempted"] is True

        # The reconciliation pause is the system's retry, not a person's: the
        # run it parks is WAITING and a clock alone may re-enter it.
        from maistro.graph.nodes.base import (
            PAUSE_AWAITING_DELEGATION_RECONCILIATION,
            PAUSE_REASON_OWNERS,
            PAUSE_RESUME_CONDITIONS,
            RESUME_ON_ELAPSED,
        )

        assert PAUSE_REASON_OWNERS[PAUSE_AWAITING_DELEGATION_RECONCILIATION] == "system"
        assert PAUSE_RESUME_CONDITIONS[PAUSE_AWAITING_DELEGATION_RECONCILIATION] == RESUME_ON_ELAPSED

    async def test_a_reconciliation_poll_recovers_the_lost_receipt(self) -> None:
        """The second invocation the recovery logic assumes. The first POST is
        lost after the peer accepted (connection dropped), so the node parks on
        reconciliation; when the tick re-enters, `reconcile` finds the receipt
        and the node pauses on the *answer* gate -- without a second POST."""
        calls = {"post": 0, "get": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                calls["post"] += 1
                raise httpx.ConnectError("connection lost after accept")
            if request.method == "GET":
                calls["get"] += 1
                return httpx.Response(200, json={"task_id": "remote-9"})
            return httpx.Response(405)

        set_test_transport(httpx.MockTransport(handler))
        peer = PeerTrust(
            peer_url="http://hub",
            peer_name="hub",
            supports_idempotency=True,
        )
        project_store = InMemoryProjectScopeStore()
        root = await project_store.create_root("workspace-1")
        project = await project_store.create(
            workspace_id="workspace-1", parent_project_id=root.project_id, name="Project"
        )
        store = InMemoryRunStore(project_store=project_store)
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        peers = GuestPeerManager()
        peers.register_peer(peer)
        node = AgentDelegateRemoteNode(guest_peers=peers, run_store=store)
        inputs = {"from_agent": "planner", "task": "x", "peer_name": "hub"}
        ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)

        first = await node.run(inputs, ctx)
        assert first.status == "paused"
        assert first.metadata["paused_reason"] == "awaiting_delegation_reconciliation"

        # The resume tick re-enters the node (same process, no answer): this is
        # a poll, not a dispatch.
        second = await node.run(inputs, ctx)

        assert second.status == "paused"
        assert second.metadata["paused_reason"] == "awaiting_remote_delegation"
        assert calls == {"post": 1, "get": 1}
        child = await store.find_delegation_run(node._delegation_key(  # type: ignore[attr-defined]
            node.input_schema.model_validate(inputs), ctx
        ))
        assert child is not None
        assert child.provenance["a2a_task_id"] == "remote-9"

    async def test_a_reconciliation_window_that_closes_fails_the_node_and_child(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A reservation nobody could reconcile is a failed delegation. The
        window is the delegation's own timeout counted from the child's durable
        creation, so once it closes without a receipt the node fails and the
        child stops claiming `created` forever."""
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        first_delegator = _FailingDelegator()
        first_delegator.register_agent_capability("planner", ["researcher"])
        inputs = {
            "from_agent": "planner",
            "task": "x",
            "to_agent": "researcher",
            "timeout_seconds": 3600,
        }
        ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)

        first = await AgentDelegateRemoteNode(a2a_delegator=first_delegator, run_store=store).run(
            inputs, ctx
        )
        assert first.status == "failed"

        second_delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=second_delegator, run_store=store)
        child = await store.find_delegation_run(
            node._delegation_key(node.input_schema.model_validate(inputs), ctx)  # type: ignore[attr-defined]
        )
        assert child is not None
        # The reconciliation window has already closed: the clock reads past
        # the child's creation plus the delegation's own timeout.
        monkeypatch.setattr(
            delegate_module,
            "now_utc",
            lambda: child.created_at + timedelta(seconds=inputs["timeout_seconds"]),
        )

        second = await node.run(inputs, ctx)

        assert second.status == "failed"
        assert second.error_code == "DelegationReconciliationExpired"
        assert "reconciled" in (second.error_message or "")
        settled = await store.get_run(child.run_id)
        assert settled is not None
        assert settled.status is RunStatus.FAILED
        assert settled.error is not None
        assert second_delegator.dispatched == []

    async def test_a_peer_that_cannot_reconcile_parks_instead_of_completing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A peer without idempotent reconciliation cannot answer a receipt
        query. The first dispatch loses the transport race (connection error);
        the reservation stays and the node parks. On re-entry the receipt
        query refuses the peer -- and that uncertainty parks the node again
        rather than completing it with an `uncertain` output the executor
        would record as a success."""

        def handler(request: httpx.Request) -> httpx.Response:
            del request
            raise httpx.ConnectError("connection lost")

        set_test_transport(httpx.MockTransport(handler))
        peer = PeerTrust(peer_url="http://hub", peer_name="hub")
        project_store = InMemoryProjectScopeStore()
        root = await project_store.create_root("workspace-1")
        project = await project_store.create(
            workspace_id="workspace-1", parent_project_id=root.project_id, name="Project"
        )
        store = InMemoryRunStore(project_store=project_store)
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        peers = GuestPeerManager()
        peers.register_peer(peer)
        node = AgentDelegateRemoteNode(guest_peers=peers, run_store=store)
        inputs = {"from_agent": "planner", "task": "x", "peer_name": "hub"}
        ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)

        first = await node.run(inputs, ctx)

        assert first.status == "paused"
        assert first.metadata["paused_reason"] == "awaiting_delegation_reconciliation"

        second = await node.run(inputs, ctx)

        assert second.status == "paused"
        assert second.metadata["paused_reason"] == "awaiting_delegation_reconciliation"
        assert "does not support idempotent" in second.metadata["error"]

    async def test_a_delegation_key_conflict_adopts_the_winner_child(self) -> None:
        """Play the SQLite unique index: a concurrent replica won the
        reservation key, this replica's INSERT bounces with the delegation-key
        integrity error, and `_reserve_child` recovers by adopting the winner
        instead of re-raising. The store in production must be left usable by
        that recovery -- which is exactly what the loser-side rollback (see
        `test_a_raised_conflict_releases_the_loser_write_lock`) provides."""
        import sqlite3

        class _DelegationKeyConflictStore(InMemoryRunStore):
            """Refuse a second child Run for any claimed delegation key."""

            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self._seen_keys: set[str] = set()

            async def create_run(self, graph: Any, **kwargs: Any) -> Any:
                provenance = kwargs.get("provenance") or {}
                key = provenance.get("delegation_key")
                if key:
                    if key in self._seen_keys:
                        raise sqlite3.IntegrityError(
                            "UNIQUE constraint failed: index 'idx_canonical_runs_delegation_key'"
                        )
                    self._seen_keys.add(key)
                return await super().create_run(graph, **kwargs)

        project_store = InMemoryProjectScopeStore()
        root = await project_store.create_root("workspace-1")
        project = await project_store.create(
            workspace_id="workspace-1", parent_project_id=root.project_id, name="Project"
        )
        store = _DelegationKeyConflictStore(project_store=project_store)
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)
        inputs = {"from_agent": "planner", "task": "x", "to_agent": "researcher"}
        ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)
        key = node._delegation_key(node.input_schema.model_validate(inputs), ctx)
        winner = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id),
            parent_run_id=parent.run_id,
            provenance={"delegation_key": key, "source": "winner-replica"},
        )

        child_id = await node._reserve_child(
            node.input_schema.model_validate(inputs),
            ctx,
            parent=parent,
            mode="in_process",
            target="researcher",
        )

        assert child_id == winner.run_id
        assert delegator.dispatched == []


class TestScopeIsCheckedBeforeDispatch:
    """`create_run` ran *after* the transport call, so a delegation naming a
    foreign Workspace was refused only once the work had already been handed
    over: the node reported failure while unauthorized work carried on
    elsewhere, and a retry dispatched it again."""

    async def test_a_foreign_workspace_is_refused_before_the_task_is_queued(self) -> None:
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)

        result = await node.run(
            {
                "from_agent": "planner",
                "task": "x",
                "to_agent": "researcher",
                "to_workspace_id": "workspace-2",
            },
            _ctx(run_id=parent.run_id),
        )

        assert result.status == "failed"
        assert result.error_code == RunIntegrityError.__name__
        assert delegator.dispatched == [], "nothing may be admitted by a refused delegation"

    async def test_an_unknown_parent_is_refused_before_the_task_is_queued(self) -> None:
        store, _project = await _spine()
        delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)

        result = await node.run(
            {"from_agent": "planner", "task": "x", "to_agent": "researcher"},
            _ctx(run_id="run-that-does-not-exist"),
        )

        assert result.status == "failed"
        assert delegator.dispatched == []

    async def test_a_delegation_in_the_parents_own_scope_still_dispatches(self) -> None:
        """The pre-flight must not become a refusal of the ordinary case."""
        store, project = await _spine()
        _node, _parent, child_run_id = await _dispatched(store, project.project_id)

        assert child_run_id


# --------------------------------------------------------------------------
# What the child records
# --------------------------------------------------------------------------


class TestWhatTheChildRecords:
    async def test_the_child_inherits_the_delegating_actor_and_persona(self) -> None:
        """Delegated work that loses its attribution cannot be audited or
        policed as the same person's, and both values were already on the
        parent record this code had just fetched."""
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id),
            persona_id="persona-7",
            actor_principal_id="user-42",
        )
        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "x", "to_agent": "researcher"},
            _ctx(run_id=parent.run_id),
        )

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        assert child.actor_principal_id == "user-42"
        assert child.persona_id == "persona-7"

    async def test_an_automatic_delegation_records_the_agent_that_was_chosen(self) -> None:
        """With `to_agent=None` the delegator selects a concrete agent. Recording
        the literal "auto" left the child's name and provenance disagreeing with
        the admitted `A2ATask.to_agent` for every automatic delegation — the case
        the field is most needed for."""
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)

        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(run_id=parent.run_id),
        )

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        assert child.provenance["target_agent"] == "researcher"
        assert "auto" not in child.graph.materialize().nodes[0].name

    async def test_the_child_snapshot_is_not_another_delegation(self) -> None:
        """A child whose only node is `agent.delegate_remote` describes the
        dispatch rather than the work: inspecting it shows a second hand-off,
        and replaying it would delegate again."""
        store, project = await _spine()
        _node, _parent, child_run_id = await _dispatched(store, project.project_id)

        child = await store.get_run(child_run_id)
        assert child is not None
        kinds = [node.node_type for node in child.graph.materialize().nodes]
        assert "agent.delegate_remote" not in kinds
        assert kinds == ["agent.remote_work"]

    async def test_an_inline_subgraph_is_snapshotted_as_the_work(self) -> None:
        """When the delegation carries the work, that is what the child records
        — rescoped into the child's Workspace and Project, because a Graph must
        agree with the Run that holds it."""
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)

        result = await node.run(
            {
                "from_agent": "planner",
                "task": "x",
                "to_agent": "researcher",
                "subgraph": {
                    "workspace_id": "somewhere-else",
                    "project_id": "some-other-project",
                    "name": "Research pipeline",
                    "nodes": [{"node_id": "summarise", "node_type": "llm.summarize"}],
                },
            },
            _ctx(run_id=parent.run_id),
        )

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        graph = child.graph.materialize()
        assert [node.node_type for node in graph.nodes] == ["llm.summarize"]
        assert graph.workspace_id == parent.workspace_id
        assert graph.project_id == parent.project_id


async def test_guest_peer_recovery_reconciles_without_a_second_post() -> None:
    calls = {"post": 0, "get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["post"] += 1
            assert request.headers["idempotency-key"]
            return httpx.Response(200, json={"task_id": "remote-1"})
        if request.method == "GET":
            calls["get"] += 1
            assert "/a2a/tasks/by-idempotency-key/" in str(request.url)
            return httpx.Response(200, json={"task_id": "remote-1"})
        return httpx.Response(405)

    set_test_transport(httpx.MockTransport(handler))
    peer = PeerTrust(
        peer_url="http://hub",
        peer_name="hub",
        supports_idempotency=True,
    )
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    project = await project_store.create(
        workspace_id="workspace-1", parent_project_id=root.project_id, name="Project"
    )
    store = _ReceiptFailingStore(project_store=project_store)
    parent = await store.create_run(
        _graph(workspace_id="workspace-1", project_id=project.project_id)
    )
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")

    first_peers = GuestPeerManager()
    first_peers.register_peer(peer)
    first_node = AgentDelegateRemoteNode(guest_peers=first_peers, run_store=store)
    inputs = {"from_agent": "planner", "task": "x", "peer_name": "hub"}
    ctx = _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id)

    first = await first_node.run(inputs, ctx)
    assert first.status == "failed"

    # A restarted replica has no process-local receipt cache. It must use the
    # peer's reconciliation endpoint instead of issuing a second POST.
    second_peers = GuestPeerManager()
    second_peers.register_peer(peer)
    second_node = AgentDelegateRemoteNode(guest_peers=second_peers, run_store=store)
    second = await second_node.run(inputs, ctx)

    assert second.status == "paused"
    assert calls == {"post": 1, "get": 1}
    assert (await store.get_run(second.metadata["run_id"])).provenance["a2a_task_id"] == "remote-1"
