"""A parked schedule Run resumes where it stopped, or stays parked (#641).

SPEC-082926-a44e. #636 gave the consumer a real yield disposition; nothing read
it back. `execute_admitted_runs` polls QUEUED only, so a Run that paused was
durably correct and permanently inert -- and the obvious repair, requeueing it,
is worse than the gap: the consumer opens a *new* NodeRun at the node's
beginning, and `agent.delegate_remote` dispatches before it pauses.

The dispatch-counting node is the load-bearing fixture here. Every other case
could be satisfied by a tick that resumed nothing at all; only a node that
counts how many times it took its dispatch branch can tell "correctly refused"
from "did nothing".
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.graph.nodes.base import (
    PAUSE_AWAITING_REMOTE_DELEGATION,
    PAUSE_RESUME_CONDITIONS,
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
    RESUME_ON_ANSWER,
    RESUME_ON_ELAPSED,
    pause_until,
    resumed_pause,
)
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_INPUTS_KEY, SCHEDULE_SOURCE
from maistro.types.config import AgentConfig

pytestmark = [pytest.mark.contract("behavioral")]

#: A reason no node raises and the table does not classify. Spelled here rather
#: than borrowed from the table, because the case under test is precisely a
#: reason the table has never heard of.
UNCLASSIFIED_REASON = "awaiting_something_nobody_declared"


class _PauseIn(BaseModel):
    marker: str = "m"


class _PauseOut(BaseModel):
    text: str


class _PollingPauseNode(BaseNode[_PauseIn, _PauseOut]):
    """Pauses on a poll reason, then completes once resumed."""

    kind: ClassVar[str] = "test.resume.polling"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = _PauseIn
    output_schema: ClassVar[type[BaseModel]] = _PauseOut
    reaches: ClassVar[int] = 0
    carried: ClassVar[dict[str, Any]] = {}

    async def _execute(self, inputs: _PauseIn, ctx: NodeContext) -> _PauseOut:
        type(self).reaches += 1
        carried = resumed_pause(ctx)
        type(self).carried = carried
        if not carried:
            pause_until(
                PAUSE_WAITING_ON_JIRA_SUBTASKS,
                resume_at=datetime.now(UTC) - timedelta(seconds=1),
                metadata={"first_seen": datetime.now(UTC).isoformat()},
            )
        return _PauseOut(text=f"resumed:{inputs.marker}")


class _DispatchingPauseNode(BaseNode[_PauseIn, _PauseOut]):
    """`agent.delegate_remote`'s shape: dispatch, then pause for the answer.

    The counter is the point. A tick that re-entered this node would take the
    dispatch branch a second time, because the answer it waits for is not
    there -- and a second dispatch is a second piece of real work sent out.
    """

    kind: ClassVar[str] = "test.resume.dispatching"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = _PauseIn
    output_schema: ClassVar[type[BaseModel]] = _PauseOut
    dispatches: ClassVar[int] = 0

    async def _execute(self, inputs: _PauseIn, ctx: NodeContext) -> _PauseOut:
        type(self).dispatches += 1
        pause_until(
            PAUSE_AWAITING_REMOTE_DELEGATION,
            resume_at=datetime.now(UTC) - timedelta(seconds=1),
            metadata={"dispatched": True},
        )
        return _PauseOut(text="unreachable")


class _UnclassifiedPauseNode(BaseNode[_PauseIn, _PauseOut]):
    """Pauses for a reason the table has never heard of."""

    kind: ClassVar[str] = "test.resume.unclassified"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = _PauseIn
    output_schema: ClassVar[type[BaseModel]] = _PauseOut
    reaches: ClassVar[int] = 0

    async def _execute(self, inputs: _PauseIn, ctx: NodeContext) -> _PauseOut:
        type(self).reaches += 1
        pause_until(
            UNCLASSIFIED_REASON,
            resume_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        return _PauseOut(text="unreachable")


for _cls in (_PollingPauseNode, _DispatchingPauseNode, _UnclassifiedPauseNode):
    with contextlib.suppress(ValueError):
        register_node(_cls)


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


async def _parked_run(container: Container, kind: str, *, workspace: str) -> str:
    """Admit a schedule Run and tick it once, so it parks the way production does.

    Built by *running* the consumer rather than by writing a parked row: a
    hand-made NodeRun and Attempt would let this suite agree with itself about
    what a pause looks like while disagreeing with the code that writes one.
    """
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="scheduled work",
        nodes=[Node(node_id="n1", node_type=kind)],
    )
    run = await container.run_store.create_run(
        graph,
        provenance={ADMISSION_SOURCE: SCHEDULE_SOURCE, SCHEDULE_INPUTS_KEY: {"marker": "m"}},
        initial_status=RunStatus.QUEUED,
    )
    assert await container.execute_admitted_runs() == 1
    parked = await container.run_store.get_run(run.run_id)
    assert parked is not None
    assert parked.status in {RunStatus.WAITING, RunStatus.PAUSED}
    return run.run_id


class TestTheTableClassifiesEveryPause:
    @pytest.mark.ac("SPEC-082926-a44e/AC-6")
    def test_every_reason_states_what_wakes_it(self) -> None:
        """An unclassified reason is not resumable, so a reason that fell out of
        the table would go quiet rather than loud. The set is pinned against the
        owners table, which the #545 structural guard already ties to the nodes."""
        from maistro.graph.nodes.base import PAUSE_REASON_OWNERS

        assert set(PAUSE_RESUME_CONDITIONS) == set(PAUSE_REASON_OWNERS)
        assert set(PAUSE_RESUME_CONDITIONS.values()) <= {RESUME_ON_ANSWER, RESUME_ON_ELAPSED}

    @pytest.mark.ac("SPEC-082926-a44e/AC-6")
    def test_every_human_pause_needs_an_answer(self) -> None:
        """A person cannot be woken by a clock. If a human reason were ever
        classified elapsed, the tick would re-enter a node that is showing
        somebody a prompt."""
        from maistro.graph.nodes.base import HUMAN_PAUSE_REASONS

        assert all(PAUSE_RESUME_CONDITIONS[r] == RESUME_ON_ANSWER for r in HUMAN_PAUSE_REASONS)

    @pytest.mark.ac("SPEC-082926-a44e/AC-6")
    def test_a_dispatching_pause_is_answer_gated_even_though_a_system_owes_it(self) -> None:
        """The reason the two tables cannot be one: `awaiting_remote_delegation`
        is owed by the *system*, and re-entering it still re-dispatches."""
        assert PAUSE_RESUME_CONDITIONS[PAUSE_AWAITING_REMOTE_DELEGATION] == RESUME_ON_ANSWER


class TestAnElapsedPollResumes:
    @pytest.mark.ac("SPEC-082926-a44e/AC-1")
    async def test_a_parked_poll_whose_time_has_passed_is_resumed(self) -> None:
        _PollingPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-1")

        assert await container.resume_parked_runs() == 1

        run = await container.run_store.get_run(run_id)
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert _PollingPauseNode.reaches == 2

    @pytest.mark.ac("SPEC-082926-a44e/AC-3")
    async def test_resuming_continues_the_parked_node_run(self) -> None:
        """One NodeRun, two Attempts. A second NodeRun would make the Run's own
        history claim the node was reached twice, which is what parking rather
        than failing was supposed to avoid."""
        _PollingPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-2")
        (before,) = await container.run_store.list_node_runs(run_id)

        await container.resume_parked_runs()

        (after,) = await container.run_store.list_node_runs(run_id)
        assert after.node_run_id == before.node_run_id
        attempts = await container.run_store.list_attempts(after.node_run_id)
        assert [a.ordinal for a in attempts] == [1, 2]
        assert attempts[0].status is AttemptStatus.YIELDED
        assert attempts[1].status is AttemptStatus.COMPLETED

    @pytest.mark.ac("SPEC-082926-a44e/AC-3")
    async def test_the_pause_metadata_reaches_the_resumed_node(self) -> None:
        """Continuing rather than restarting is only true if the node can tell.
        Without its own pause record back, a polling node takes its first-reach
        branch again and its deadline can never be reached."""
        _PollingPauseNode.reaches = 0
        _PollingPauseNode.carried = {}
        container = await _container()
        await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-3")

        await container.resume_parked_runs()

        assert _PollingPauseNode.carried.get("first_seen")
        assert _PollingPauseNode.carried["paused_reason"] == PAUSE_WAITING_ON_JIRA_SUBTASKS


class TestAnAnswerGatedPauseIsLeftAlone:
    @pytest.mark.ac("SPEC-082926-a44e/AC-2")
    @pytest.mark.ac("SPEC-082926-a44e/AC-4")
    async def test_a_dispatched_delegation_is_not_dispatched_again(self) -> None:
        """The criterion the whole classification exists for. The pause's
        `resume_at` is already in the past, so a tick that read the timer alone
        would re-enter the node and send a second delegation."""
        _DispatchingPauseNode.dispatches = 0
        container = await _container()
        run_id = await _parked_run(container, _DispatchingPauseNode.kind, workspace="resume-ws-4")
        assert _DispatchingPauseNode.dispatches == 1

        assert await container.resume_parked_runs() == 0

        assert _DispatchingPauseNode.dispatches == 1
        run = await container.run_store.get_run(run_id)
        assert run is not None
        assert run.status in {RunStatus.WAITING, RunStatus.PAUSED}


class TestAnUnclassifiedPauseStaysParked:
    @pytest.mark.ac("SPEC-082926-a44e/AC-5")
    async def test_a_reason_the_table_does_not_know_is_left_parked_and_visible(self) -> None:
        """Not resumed, and not terminalized either: parked and visible is the
        honest record for a wait nobody has said how to end."""
        _UnclassifiedPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _UnclassifiedPauseNode.kind, workspace="resume-ws-5")

        assert await container.resume_parked_runs() == 0

        assert _UnclassifiedPauseNode.reaches == 1
        run = await container.run_store.get_run(run_id)
        assert run is not None
        assert run.status in {RunStatus.WAITING, RunStatus.PAUSED}


class TestWhatTheTickRefusesToTouch:
    async def test_a_parked_run_from_another_source_is_not_ours(self) -> None:
        """The parked mirror of the QUEUED allowlist. A Run parked by another
        producer belongs to whoever admitted it."""
        _PollingPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-6")
        run = await container.run_store.get_run(run_id)
        assert run is not None
        stored = container.run_store._runs[run_id]  # type: ignore[attr-defined]
        container.run_store._runs[run_id] = stored.model_copy(  # type: ignore[attr-defined]
            update={"provenance": {ADMISSION_SOURCE: "some.other.producer"}}
        )

        assert await container.resume_parked_runs() == 0

    async def test_a_pause_whose_time_has_not_come_is_left_parked(self) -> None:
        _PollingPauseNode.reaches = 0
        container = await _container()
        await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-7")

        resumed = await container.resume_parked_runs(now=datetime.now(UTC) - timedelta(minutes=5))

        assert resumed == 0
        assert _PollingPauseNode.reaches == 1

    async def test_a_failed_park_is_not_a_pause_to_resume(self) -> None:
        """A FAILED Attempt parks its NodeRun WAITING too, and that park means a
        retry decision is owed -- somebody else's call, not this tick's."""
        from maistro.runs.consumption import resumable_pause
        from maistro.runs.model import Attempt, NodeRun

        node_run = NodeRun(run_id="r", node_id="n1", ordinal=1, status=RunStatus.WAITING)
        failed = Attempt(
            node_run_id=node_run.node_run_id,
            ordinal=1,
            status=AttemptStatus.FAILED,
            result={"paused_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS, "resume_at": None},
            finished_at=datetime.now(UTC),
        )

        assert resumable_pause(node_run, [failed], now=datetime.now(UTC)) is None


class TestThePollDeadlineCanNowBeReached:
    @pytest.mark.ac("SPEC-082926-a44e/AC-6")
    async def test_a_resumed_jira_wait_reports_its_own_timeout(self, monkeypatch) -> None:
        """`wait_first_seen:<node_id>` was read and never written -- by anything
        but tests. So the node took its first-reach branch on every real path
        and the deadline it recorded could not be reached: a poll that never
        expires, which a resume tick turns into an unbounded loop."""
        from maistro.graph.nodes.base import RESUMED_PAUSE_KEY
        from maistro.graph.nodes.jira_wait_for_subtasks import JiraWaitForSubtasksNode

        node = JiraWaitForSubtasksNode()
        long_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        ctx = NodeContext(
            run_id="r",
            dag_id="d",
            node_id="n1",
            metadata={RESUMED_PAUSE_KEY: {"first_seen": long_ago}},
        )

        async def _statuses(*_args: Any, **_kwargs: Any) -> dict[str, str]:
            return {"PROJ-1": "In Progress"}

        import maistro.graph.nodes.jira_wait_for_subtasks as jira_module

        monkeypatch.setattr(jira_module, "_fetch_subtask_statuses", _statuses)
        result = await node.run(
            {
                "base_url": "https://jira.example.com",
                "parent_key": "PROJ-100",
                "pat": "x",
                "timeout_seconds": 60,
            },
            ctx,
        )

        assert result.status == "completed"
        assert result.output is not None
        assert result.output.timed_out is True
