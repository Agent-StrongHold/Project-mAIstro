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

import asyncio
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
from maistro.runs.store import RunIntegrityError
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


class _FailingNode(BaseNode[_PauseIn, _PauseOut]):
    """Fails, so its Run parks WAITING and is never resumable.

    The backlog this tick has to see past. A failure's park means a retry
    decision is owed, which is somebody else's to take.
    """

    kind: ClassVar[str] = "test.resume.failing"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PauseIn
    output_schema: ClassVar[type[BaseModel]] = _PauseOut
    reaches: ClassVar[int] = 0

    async def _execute(self, inputs: _PauseIn, ctx: NodeContext) -> _PauseOut:
        type(self).reaches += 1
        raise RuntimeError("this node always fails")


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


for _cls in (_PollingPauseNode, _DispatchingPauseNode, _UnclassifiedPauseNode, _FailingNode):
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


class TestTheTickUnderStress:
    async def test_two_ticks_resume_one_parked_run_once(self) -> None:
        """The claim is the parked->RUNNING transition, exactly as the QUEUED
        tick's claim is QUEUED->RUNNING. The transition table is the mutex, so
        the loser skips rather than resuming the same NodeRun twice."""
        _PollingPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-8")

        first, second = await asyncio.gather(
            container.resume_parked_runs(),
            container.resume_parked_runs(),
        )

        assert first + second == 1
        assert _PollingPauseNode.reaches == 2
        (node_run,) = await container.run_store.list_node_runs(run_id)
        attempts = await container.run_store.list_attempts(node_run.node_run_id)
        assert len(attempts) == 2

    async def test_a_resume_that_fails_outright_leaves_the_run_parked(self, monkeypatch) -> None:
        """Not RUNNING over a parked NodeRun. Nothing about the pause has
        changed, so the honest record is the one the resume found, and the next
        tick may try again."""
        _PollingPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-9")
        parked_before = await container.run_store.get_run(run_id)
        assert parked_before is not None

        async def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("the resolver blew up before any Attempt existed")

        monkeypatch.setattr("maistro.runs.consumption.ScheduleAttemptExecutor.resume", _boom)

        await container.resume_parked_runs()

        run = await container.run_store.get_run(run_id)
        assert run is not None
        assert run.status is parked_before.status
        (node_run,) = await container.run_store.list_node_runs(run_id)
        assert len(await container.run_store.list_attempts(node_run.node_run_id)) == 1

    async def test_a_run_with_more_than_one_node_run_is_not_resumed(self) -> None:
        """Two NodeRuns for a single-node Run means the node was restarted
        somewhere, which is the state this tick exists to avoid creating.
        Guessing which one to continue would compound it."""
        _PollingPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-10")
        await container.run_store.create_node_run(run_id, node_id="n1")

        assert await container.resume_parked_runs() == 0
        assert _PollingPauseNode.reaches == 1


class TestWhatCountsAsAReadablePause:
    """`resumable_pause`'s refusals, each of which is a real durable state.

    Direct rather than through the tick: every one of these is a row the tick
    would have to be handed, and building five parked Runs to reach five guards
    would test the fixture rather than the rule.
    """

    def _attempt(self, node_run: Any, result: Any, *, status: AttemptStatus) -> Any:
        from maistro.runs.model import Attempt

        return Attempt(
            node_run_id=node_run.node_run_id,
            ordinal=1,
            status=status,
            result=result,
            finished_at=datetime.now(UTC),
        )

    def _parked_node_run(self, status: RunStatus = RunStatus.WAITING) -> Any:
        from maistro.runs.model import NodeRun

        return NodeRun(run_id="r", node_id="n1", ordinal=1, status=status)

    def test_a_running_node_run_is_not_parked(self) -> None:
        from maistro.runs.consumption import resumable_pause

        node_run = self._parked_node_run(RunStatus.RUNNING)

        assert resumable_pause(node_run, [], now=datetime.now(UTC)) is None

    def test_a_parked_node_run_with_no_attempts_has_no_pause_to_read(self) -> None:
        """A pause is a thing an Attempt recorded. Without one there is nothing
        saying what this NodeRun waits for, and inventing an answer is worse
        than leaving it visible."""
        from maistro.runs.consumption import resumable_pause

        assert resumable_pause(self._parked_node_run(), [], now=datetime.now(UTC)) is None

    def test_a_yielded_attempt_whose_result_is_not_a_record_is_not_read(self) -> None:
        """`result` is free-form on the model. A yielded Attempt carrying a bare
        value says nothing about what it waits for."""
        from maistro.runs.consumption import resumable_pause

        node_run = self._parked_node_run()
        attempt = self._attempt(node_run, "paused", status=AttemptStatus.YIELDED)

        assert resumable_pause(node_run, [attempt], now=datetime.now(UTC)) is None

    def test_a_pause_with_no_usable_resume_time_is_not_elapsed(self) -> None:
        """Absent, or a value that is not a timestamp. Either way there is no
        moment to compare against, and "no stated time" must not read as "any
        time will do"."""
        from maistro.runs.consumption import _pause_from_attempt

        node_run = self._parked_node_run()
        for raw in (None, 12345, "not-a-timestamp"):
            attempt = self._attempt(
                node_run,
                {"paused_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS, "resume_at": raw},
                status=AttemptStatus.YIELDED,
            )
            pause = _pause_from_attempt(node_run, attempt)

            assert pause is not None
            assert pause.resume_at is None
            assert pause.elapsed(datetime.now(UTC)) is False

    def test_a_naive_resume_time_is_read_as_utc(self) -> None:
        """A store that dropped the offset must not make the comparison raise;
        UTC is what every writer here records."""
        from maistro.runs.consumption import _pause_from_attempt

        node_run = self._parked_node_run()
        attempt = self._attempt(
            node_run,
            {
                "paused_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS,
                "resume_at": datetime(2020, 1, 1, 12, 0).isoformat(),
            },
            status=AttemptStatus.YIELDED,
        )

        pause = _pause_from_attempt(node_run, attempt)

        assert pause is not None
        assert pause.resume_at == datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
        assert pause.elapsed(datetime.now(UTC)) is True


class TestTheClaimAndTheWayBack:
    """The tick's two failure paths, forced rather than raced.

    `asyncio.gather` on an in-memory store does not reliably interleave two
    ticks at the transition, so the concurrency test above can pass by the
    "second tick saw nothing parked" route without ever exercising the lost
    claim. Making the claim fail outright is the same fact, deterministically:
    the transition table refused, so this Run is not ours.
    """

    async def test_a_tick_that_loses_the_claim_resumes_nothing(self, monkeypatch) -> None:
        _PollingPauseNode.reaches = 0
        container = await _container()
        await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-11")

        async def refuse(*_args: Any, **_kwargs: Any) -> None:
            raise RunIntegrityError("another tick already claimed this Run")

        monkeypatch.setattr(container.run_store, "transition_run", refuse)

        assert await container.resume_parked_runs() == 0
        assert _PollingPauseNode.reaches == 1

    async def test_a_running_node_run_with_no_live_attempt_is_re_parked(self, monkeypatch) -> None:
        """The state `prepare_execution` can leave behind (#666 review).

        It un-parks the NodeRun *before* the Attempt is created, so a failure in
        between leaves a RUNNING NodeRun with nothing running under it. That is
        invisible to both ticks -- this one looks for parked Runs, and
        abandoned-attempt recovery looks for Attempts, of which there are none.
        Left alone the Run is RUNNING forever, which is why "the NodeRun says
        RUNNING" is not on its own a reason to stand back.

        An earlier version of this test asserted the opposite and was wrong.
        """
        _PollingPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-12")
        (node_run,) = await container.run_store.list_node_runs(run_id)

        async def start_then_fail(self: Any, run: Any, pause: Any) -> None:
            await container.run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
            raise RuntimeError("the store refused the Attempt after preparation")

        monkeypatch.setattr(
            "maistro.runs.consumption.ScheduleAttemptExecutor.resume", start_then_fail
        )

        await container.resume_parked_runs()

        run = await container.run_store.get_run(run_id)
        settled = await container.run_store.get_node_run(node_run.node_run_id)
        assert run is not None and run.status is RunStatus.WAITING
        assert settled is not None and settled.status is RunStatus.WAITING

    async def test_a_live_attempt_is_left_to_the_recovery_tick(self, monkeypatch) -> None:
        """The other half. Something is genuinely executing, or died holding a
        lease; either way abandoned-attempt recovery owns it, and re-parking the
        Run over a live Attempt would say the work stopped when it had not."""
        _PollingPauseNode.reaches = 0
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-12b")
        (node_run,) = await container.run_store.list_node_runs(run_id)

        async def start_an_attempt_then_fail(self: Any, run: Any, pause: Any) -> None:
            await container.run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
            attempt = await container.run_store.create_attempt(
                node_run.node_run_id, executor_id="probe"
            )
            lease = attempt.execution_lease
            await container.run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.RUNNING,
                fencing_token=lease.fencing_token if lease else None,
            )
            raise RuntimeError("the executor died with its Attempt still open")

        monkeypatch.setattr(
            "maistro.runs.consumption.ScheduleAttemptExecutor.resume",
            start_an_attempt_then_fail,
        )

        await container.resume_parked_runs()

        run = await container.run_store.get_run(run_id)
        assert run is not None and run.status is RunStatus.RUNNING

    async def test_a_failing_re_park_is_logged_rather_than_raised(
        self, monkeypatch, caplog
    ) -> None:
        """The tick is a loop over many Runs. A store that refuses the way back
        for one of them must not take the other ninety-nine with it."""
        import logging

        _PollingPauseNode.reaches = 0
        container = await _container()
        await _parked_run(container, _PollingPauseNode.kind, workspace="resume-ws-13")

        async def boom_resume(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("resume failed")

        async def boom_read(*_args: Any, **_kwargs: Any) -> None:
            raise RunIntegrityError("the store is unreachable")

        monkeypatch.setattr("maistro.runs.consumption.ScheduleAttemptExecutor.resume", boom_resume)
        monkeypatch.setattr(container.run_store, "get_node_run", boom_read)

        with caplog.at_level(logging.WARNING, logger="maistro.container"):
            assert await container.resume_parked_runs() == 1

        assert "could not be re-parked" in caplog.text


class TestTheTickIsNotStarvedByWhatItCannotResume:
    """The backlog is the steady state, not an edge case (#666 review).

    Every Run parked by a *failed* Attempt sits WAITING until somebody decides
    to retry it, and `list_by_status` is oldest-first. So asking for `limit`
    rows and filtering afterwards meant a standing backlog of ineligible rows
    made every tick inspect the same ones and never reach a resumable Run —
    permanently, not until it cleared.
    """

    async def _failed_parked_run(self, container: Container, index: int) -> str:
        """A Run parked WAITING by a failure, which is never resumable."""
        run_id = await _parked_run(container, _FailingNode.kind, workspace=f"starve-ws-{index}")
        return run_id

    async def test_a_backlog_of_failures_does_not_hide_a_resumable_poll(self) -> None:
        _FailingNode.reaches = 0
        _PollingPauseNode.reaches = 0
        container = await _container()
        for index in range(4):
            await self._failed_parked_run(container, index)
        await _parked_run(container, _PollingPauseNode.kind, workspace="starve-ws-live")

        # A work limit smaller than the backlog. Before the fix the scan was
        # bounded by this same number, so the poll behind four failures was
        # invisible however many times the tick ran.
        assert await container.resume_parked_runs(limit=1) == 1
        assert _PollingPauseNode.reaches == 2

    async def test_the_work_limit_still_bounds_what_one_tick_resumes(self) -> None:
        """The scan is wide; the work is not. A tick that resumed everything it
        could see would be unbounded, which is the discipline ADR-019 sets."""
        _PollingPauseNode.reaches = 0
        container = await _container()
        for index in range(3):
            await _parked_run(container, _PollingPauseNode.kind, workspace=f"bound-ws-{index}")

        assert await container.resume_parked_runs(limit=2) == 2
        assert _PollingPauseNode.reaches == 5  # 3 first reaches + 2 resumes


class TestTheScanRotatesRatherThanAlwaysStartingOver:
    """Raising the scan bound moved the starvation cliff; it did not remove it.

    Past `RESUME_SCAN_LIMIT` permanently-ineligible rows the tick is back to
    inspecting the same prefix every time, and the warning that says so is a
    description rather than a fix (#666 review, second round). The scan now
    resumes where the last one stopped and wraps at the end, so every parked
    Run is reached within one lap however long the prefix grows.
    """

    async def test_a_resumable_run_behind_a_full_scan_page_is_reached_on_a_later_tick(
        self, monkeypatch
    ) -> None:
        """The case a bigger constant cannot answer. The scan page is shrunk to
        two rather than the backlog grown past a thousand, because what is under
        test is the rotation, and a test that needed 1001 rows to see it would
        be measuring the constant instead."""
        import maistro.container as container_module

        monkeypatch.setattr(container_module, "RESUME_SCAN_LIMIT", 2)
        _FailingNode.reaches = 0
        _PollingPauseNode.reaches = 0
        container = await _container()
        for index in range(4):
            await _parked_run(container, _FailingNode.kind, workspace=f"rotate-ws-{index}")
        await _parked_run(container, _PollingPauseNode.kind, workspace="rotate-ws-live")

        # Tick 1 sees rows 0-1, tick 2 rows 2-3: four ineligible failures, and
        # a fixed oldest-first page of two would have stopped at the first pair
        # forever.
        assert await container.resume_parked_runs(limit=1) == 0
        assert await container.resume_parked_runs(limit=1) == 0
        assert await container.resume_parked_runs(limit=1) == 1
        assert _PollingPauseNode.reaches == 2

    async def test_the_cursor_wraps_so_the_oldest_rows_are_seen_again(self, monkeypatch) -> None:
        """A cursor that only advanced would starve the front of the list
        instead of the back — the same defect facing the other way."""
        import maistro.container as container_module

        monkeypatch.setattr(container_module, "RESUME_SCAN_LIMIT", 2)
        _PollingPauseNode.reaches = 0
        container = await _container()
        await _parked_run(container, _PollingPauseNode.kind, workspace="wrap-ws-0")
        for index in range(3):
            await _parked_run(container, _FailingNode.kind, workspace=f"wrap-ws-f{index}")

        # Lap the cursor past the end and back round to the resumable row.
        resumed = [await container.resume_parked_runs(limit=1) for _ in range(4)]

        assert sum(resumed) >= 1, "the oldest row was never revisited"


class TestAnAttemptThatNeverStartedIsNotSomethingRunning:
    @pytest.mark.ac("SPEC-082926-a44e/AC-3")
    async def test_a_created_attempt_does_not_hold_the_run_claimed(self) -> None:
        """`prepare_execution` persists the Attempt and then transitions it; an
        exception in between leaves it `CREATED`. Treating merely-non-terminal
        as live read that as somebody else's work — and nobody's it was:
        `ScheduleAttemptExecutor` sets no lease TTL, so nothing expires it and
        no recovery tick reclaims it. The Run stayed RUNNING for ever (#666
        review, second round).
        """
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="created-ws")
        run = await container.run_store.get_run(run_id)
        assert run is not None
        parked_as = run.status
        (node_run,) = await container.run_store.list_node_runs(run_id)

        await container.run_store.transition_run(run_id, RunStatus.RUNNING)
        await container.run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        await container.run_store.create_attempt(node_run.node_run_id)

        await container._repark_after_failed_resume(run_id, node_run.node_run_id, parked_as)

        settled = await container.run_store.get_run(run_id)
        assert settled is not None
        assert settled.status is parked_as, "a CREATED Attempt held the Run claimed"

    async def test_a_running_attempt_is_still_left_to_the_recovery_tick(self) -> None:
        """The other direction, and the reason this is not simply 'always
        re-park': an Attempt that is genuinely RUNNING, or died holding a lease,
        belongs to abandoned-attempt recovery."""
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="running-ws")
        run = await container.run_store.get_run(run_id)
        assert run is not None
        parked_as = run.status
        (node_run,) = await container.run_store.list_node_runs(run_id)

        await container.run_store.transition_run(run_id, RunStatus.RUNNING)
        await container.run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        attempt = await container.run_store.create_attempt(node_run.node_run_id)
        await container.run_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)

        await container._repark_after_failed_resume(run_id, node_run.node_run_id, parked_as)

        settled = await container.run_store.get_run(run_id)
        assert settled is not None
        assert settled.status is RunStatus.RUNNING


class TestThePauseIsRereadAfterTheClaim:
    async def test_a_pause_that_moved_between_the_read_and_the_claim_is_not_used(
        self, monkeypatch
    ) -> None:
        """Two replicas read the same elapsed pause. The first resumes, yields
        again with a later `resume_at`, and parks it back; the second's claim
        then succeeds because the Run is parked once more. Resuming on the pause
        it read *beforehand* polls immediately instead of honouring the delay
        just recorded — every replica collapsing the interval into a burst,
        which is the one thing a poll deadline exists to prevent (#666 review,
        second round).
        """
        container = await _container()
        run_id = await _parked_run(container, _PollingPauseNode.kind, workspace="stale-ws")
        _PollingPauseNode.reaches = 0

        real = Container._resumable_pause_for
        calls: list[int] = []

        async def _moves_after_the_first_read(self, run, moment):
            calls.append(1)
            # The second call is the one made after the claim: answer None, as
            # a pause whose deadline has moved into the future would.
            if len(calls) >= 2:
                return None
            return await real(self, run, moment)

        monkeypatch.setattr(Container, "_resumable_pause_for", _moves_after_the_first_read)

        assert await container.resume_parked_runs() == 0
        assert _PollingPauseNode.reaches == 0, "resumed on a pause that had moved"

        settled = await container.run_store.get_run(run_id)
        assert settled is not None
        assert settled.status is not RunStatus.RUNNING, "left claimed with nothing running"

    async def test_the_pause_handed_to_the_executor_is_the_one_read_after_the_claim(
        self, monkeypatch
    ) -> None:
        """The half the None case cannot see, and the reason it is not enough.

        Answering None after the claim exercises the guard but not the choice:
        with the re-read discarded and the earlier pause passed on, that test
        still passes, because it never reaches the line that picks one. This
        one asserts by identity which object the executor was handed.
        """
        from maistro.runs.consumption import ScheduleAttemptExecutor

        container = await _container()
        await _parked_run(container, _PollingPauseNode.kind, workspace="fresh-ws")

        real = Container._resumable_pause_for
        seen: list[Any] = []

        async def _reads(self, run, moment):
            pause = await real(self, run, moment)
            seen.append(pause)
            return pause

        handed: list[Any] = []

        async def _capture(self, run, pause):
            handed.append(pause)

        monkeypatch.setattr(Container, "_resumable_pause_for", _reads)
        monkeypatch.setattr(ScheduleAttemptExecutor, "resume", _capture)

        assert await container.resume_parked_runs() == 1

        assert len(seen) == 2, "the pause was not re-read after the claim"
        assert handed and handed[0] is seen[1], "the executor got the pre-claim pause"


class TestAMultiNodeRunIsNotThisTicksToResume:
    @pytest.mark.ac("SPEC-082926-a44e/AC-5")
    async def test_a_multi_node_parked_run_is_left_alone(self) -> None:
        """`unresolvable_reason` answers `None` for a multi-node graph on
        purpose — it is owed to the durable Graph traversal, not unrunnable. So
        a multi-node Run parked at its first pause has exactly one NodeRun and
        passed every other check; the tick claimed it, `_single_node` raised,
        and the warning repeated forever without the graph advancing.
        """
        from maistro.runs.consumption import resumable_by_consumer

        container = await _container()
        root = await container.project_scope_store.create_root("multi-ws")
        graph = Graph(
            workspace_id="multi-ws",
            project_id=root.project_id,
            name="two nodes",
            nodes=[
                Node(node_id="n1", node_type=_PollingPauseNode.kind),
                Node(node_id="n2", node_type=_PollingPauseNode.kind),
            ],
        )
        run = await container.run_store.create_run(
            graph,
            provenance={ADMISSION_SOURCE: SCHEDULE_SOURCE},
            initial_status=RunStatus.QUEUED,
        )
        await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
        await container.run_store.transition_run(run.run_id, RunStatus.WAITING)
        parked = await container.run_store.get_run(run.run_id)
        assert parked is not None

        assert resumable_by_consumer(parked) is False
        assert await container.resume_parked_runs() == 0
