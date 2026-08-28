"""A chat Run is never left QUEUED with nobody to finish it (#338).

`_admit_chat_turn` creates the Run, transitions it to QUEUED, then to RUNNING.
The QUEUED write is durable, and every failure after it used to be swallowed
into `return None` -- which meant `_close_chat_run` received None and did
nothing, and no sweeper owns a non-terminal Run. One transient store error, and
a row sat QUEUED for the life of the database, read by recovery as work still
to do.

The rule these cover is that a Run which exists is a Run somebody finishes. The
failure is injected after *each* step, because "we handled the one we found" is
how the next one goes unnoticed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.container import Container, create_container
from maistro.runs.chat_admission import NEVER_DISPATCHED, stranded_chat_runs_total
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.types.config import AgentConfig

MESSAGES = [{"role": "user", "content": "hi"}]


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


def _stranded_count() -> float:
    """The counter's unlabelled total. Read as a delta by its callers, because
    the registry is process-wide and other tests share it."""
    return sum(sample["value"] for sample in stranded_chat_runs_total.collect())


class _FailAfter:
    """A `transition_run` that raises once it has seen `after` transitions.

    Wraps the real store rather than replacing it, so every transition before
    the injected one is genuinely persisted -- which is the whole point: the
    stranded Run in the defect is one the store really did write.

    `transient` (the default) fails exactly one transition and then recovers,
    which is the blip these tests are about: the compensating write has to be
    able to land, or the test cannot observe it. `transient=False` keeps the
    store down for good, which is the harder case covered at the bottom.

    It also records every Run id it was asked to transition. `RunStore` has no
    listing method and the failing call returns None, so those ids are the only
    handle a test has on the row left behind -- which is exactly the position a
    recovery sweeper would be in.

    Note the admitter is *not* wrapped: `ChatRunAdmitter` captured its own
    reference to the store when the container was wired, so `admit` still
    creates the Run through the real one. That is the arrangement under test --
    the Run really exists before anything this wrapper can fail.
    """

    def __init__(
        self, store: Any, *, after: int, error: BaseException, transient: bool = True
    ) -> None:
        self._store = store
        self._after = after
        self._error = error
        self._transient = transient
        self.seen = 0
        self.touched: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def transition_run(self, run_id: str, status: RunStatus, **kwargs: Any) -> Any:
        self.touched.append(run_id)
        self.seen += 1
        failing = self.seen > self._after and (not self._transient or self.seen == self._after + 1)
        if failing:
            raise self._error
        return await self._store.transition_run(run_id, status, **kwargs)


async def _only_run(container: Container) -> Any:
    """The one Run this turn created, read back from the store."""
    touched = set(container.run_store.touched)
    assert len(touched) == 1, container.run_store.touched
    run = await container.run_store.get_run(next(iter(touched)))
    assert run is not None
    return run


class TestAFailureAfterAdmissionLeavesNoOpenRun:
    @pytest.mark.parametrize("after", [0, 1])
    async def test_a_store_error_terminalizes_the_run_it_stranded(self, after: int) -> None:
        """`after=0` fails the QUEUED write, `after=1` the RUNNING write.

        Both are after the Run exists, which is what makes them strandable; the
        second is the exact path the issue reports.
        """
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store, after=after, error=RuntimeError("store is down")
        )

        admitted = await container._admit_chat_turn(MESSAGES)

        assert admitted is None
        run = await _only_run(container)
        assert run.status in TERMINAL_RUN_STATUSES
        assert run.status is RunStatus.CANCELLED

    async def test_the_terminal_run_says_it_never_ran(self) -> None:
        """`never_dispatched`, not `internal_error`: nothing executed, so there
        is no partial effect to reason about and nothing to retry against."""
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store, after=1, error=RuntimeError("store is down")
        )

        await container._admit_chat_turn(MESSAGES)

        assert (await _only_run(container)).error == NEVER_DISPATCHED

    async def test_no_exception_text_reaches_the_record(self) -> None:
        """`/runs/{run_id}` hands `Run.error` to anyone holding the id, and a
        store error's message can carry a DSN."""
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store,
            after=1,
            error=RuntimeError("connection to postgresql://user:hunter2@db/maistro failed"),
        )

        await container._admit_chat_turn(MESSAGES)

        assert "hunter2" not in ((await _only_run(container)).error or "")


class TestCancellationStrandsNothingEither:
    async def test_a_disconnect_between_queued_and_running_still_terminalizes(self) -> None:
        """`CancelledError` is not an `Exception`, so it passed straight through
        the handler that was supposed to catch this -- leaving the same open Run
        by a route the original fix did not cover."""
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store, after=1, error=asyncio.CancelledError()
        )

        with pytest.raises(asyncio.CancelledError):
            await container._admit_chat_turn(MESSAGES)

        run = await _only_run(container)
        assert run.status is RunStatus.CANCELLED
        assert run.error == NEVER_DISPATCHED

    async def test_the_cancellation_is_re_raised_rather_than_absorbed(self) -> None:
        """Compensating is not the same as continuing. Swallowing the
        cancellation would tell the caller the turn is still on its way."""
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store, after=1, error=asyncio.CancelledError()
        )

        with pytest.raises(asyncio.CancelledError):
            await container._admit_chat_turn(MESSAGES)


class TestCompensationIsIdempotent:
    async def test_compensating_a_run_that_is_already_terminal_is_a_no_op(self) -> None:
        """Two compensations can race -- one from the failure path, one from a
        retry of the same turn -- and the second must settle, not raise."""
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store, after=1, error=RuntimeError("store is down")
        )
        await container._admit_chat_turn(MESSAGES)
        run = await _only_run(container)

        await container._abandon_chat_run(run)
        await container._abandon_chat_run(run)

        settled = await _only_run(container)
        assert settled.status is RunStatus.CANCELLED
        assert settled.error == NEVER_DISPATCHED

    async def test_concurrent_compensations_leave_one_terminal_state(self) -> None:
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store, after=1, error=RuntimeError("store is down")
        )
        await container._admit_chat_turn(MESSAGES)
        run = await _only_run(container)

        results = await asyncio.gather(
            container._abandon_chat_run(run),
            container._abandon_chat_run(run),
            container._abandon_chat_run(run),
            return_exceptions=True,
        )

        assert [r for r in results if isinstance(r, BaseException)] == []
        assert (await _only_run(container)).status is RunStatus.CANCELLED


class TestTheOrdinaryPathIsUnchanged:
    async def test_a_successful_admission_still_reaches_running(self) -> None:
        """The compensation must not fire on the path that works."""
        container = await _container()

        run = await container._admit_chat_turn(MESSAGES)

        assert run is not None
        assert run.status is RunStatus.RUNNING
        assert run.error is None

    async def test_no_run_is_created_when_the_admitter_itself_fails(self) -> None:
        """Nothing to compensate, and nothing stranded: the failure happened
        before any Run existed. Compensation must not invent one."""
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store, after=99, error=RuntimeError("never reached")
        )

        async def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("admission is down")

        assert container.chat_admitter is not None
        container.chat_admitter.admit = refuse  # type: ignore[method-assign]

        assert await container._admit_chat_turn(MESSAGES) is None
        # Nothing reached a transition, so nothing was ever QUEUED and
        # there is no row for compensation to have missed.
        assert container.run_store.touched == []

    async def test_an_unwired_admitter_is_still_not_an_error(self) -> None:
        """A turn is never refused for want of a Run -- the rule this path had
        before #338 and still has."""
        container = await _container()
        container.chat_admitter = None  # type: ignore[assignment]

        assert await container._admit_chat_turn(MESSAGES) is None


class TestTheResidualCaseIsCountedRatherThanHidden:
    """Compensation is a write, and a write can fail too.

    Nothing can rule that out from inside the process -- if the store is gone,
    it is gone. What #338's DoD asks for is that the leftover is *countable*
    rather than only greppable, so a sweeper or an operator can see that Runs
    were left non-terminal and how many.
    """

    async def test_a_store_that_stays_down_increments_the_stranded_counter(self) -> None:
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store,
            after=1,
            error=RuntimeError("store is down"),
            transient=False,
        )
        before = _stranded_count()

        await container._admit_chat_turn(MESSAGES)

        assert _stranded_count() == before + 1

    async def test_the_turn_still_answers_when_compensation_fails(self) -> None:
        """A turn is never refused for want of a Run, and that rule survives
        compensation failing: the caller gets None and carries on."""
        container = await _container()
        container.run_store = _FailAfter(
            container.run_store,
            after=1,
            error=RuntimeError("store is down"),
            transient=False,
        )

        assert await container._admit_chat_turn(MESSAGES) is None
