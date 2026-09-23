"""A schedule firing becomes a Run that knows it came from a schedule (#145, #46).

`test_engine.py` covers `evaluate()` as the pure function it is. What could not
be asserted there is everything that happens *around* the decision: the Run
carries the Schedule's identity, the cursor moves only after the Run exists,
and a schedule that reaches `max_runs` is disabled in the same write that
records its last fire.

Every one of those was previously unobservable. A scheduled Run recorded no
`admission_source`, no `schedule_id` and no nominal fire time — the linkage
lived in an audit line beside the Run — and `ScheduleStore.record_fire`,
`max_runs` and `last_run_id` were implemented, tested against the store, and
called by nobody.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph.definitions import GraphTemplate, Node
from maistro.graph.templates import GraphTemplateNotFound, InMemoryGraphTemplateStore
from maistro.observability.correlation import bind_execution_context
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import Run, RunStatus
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_INPUTS_KEY,
    SCHEDULE_SOURCE,
    SCHEDULE_TRIGGER_KEY,
    SCHEDULE_TRIGGER_RECURRING,
    SCHEDULED_FOR_KEY,
)
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.scheduling.admission import (
    REQUEST_ID_KEY,
    ManualFireRefused,
    ScheduleAdmission,
    ScheduleRunAdmitter,
)
from maistro.scheduling.engine import FireDecision, SkipReason
from maistro.scheduling.model import OverlapPolicy, Schedule
from maistro.scheduling.store import InMemoryScheduleStore

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
TEMPLATE_ID = "daily-status"


@pytest.fixture
async def harness():
    """A run store on a real Project, a template store holding one template,
    and a schedule store — the three the admitter ties together."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    project = await projects.create(
        workspace_id="w1", parent_project_id=root.project_id, name="Scheduled"
    )
    runs = InMemoryRunStore(project_store=projects)
    templates = InMemoryGraphTemplateStore()
    await templates.put(
        GraphTemplate(
            template_id=TEMPLATE_ID,
            workspace_id="w1",
            version=1,
            name="daily status",
            nodes=[Node(node_id="n1", node_type="agent", name="a")],
        )
    )
    schedules = InMemoryScheduleStore()
    return (
        ScheduleRunAdmitter(runs, templates, schedules),
        runs,
        templates,
        schedules,
        project.project_id,
    )


async def _schedule(schedules, project_id: str, **overrides: object) -> Schedule:
    defaults: dict[str, object] = {
        "workspace_id": "w1",
        "project_id": project_id,
        "name": "hourly",
        "cron": "0 * * * *",
        "graph_template_id": TEMPLATE_ID,
        # Real schedules predate the moment they are evaluated; the default
        # factory would stamp *now*, which is after these fixed instants.
        "created_at": NOON - timedelta(days=30),
        "last_fired_at": NOON - timedelta(hours=1),
    }
    return await schedules.put(Schedule(**{**defaults, **overrides}))  # type: ignore[arg-type]


class _UnresolvableOccurrenceWinner:
    """A run store whose occurrence index cannot answer one claim.

    In a consistent store the `DuplicateOccurrence` raise site and the
    occurrence index are the same map, so no real sequence can refuse an
    insert and then fail to resolve the winner — the branch the admitter
    carries for this exists because a backend's claim check and its index can
    come apart (a partially restored replica, a migration that rebuilt the
    index). Only the one lookup is intercepted; everything else delegates to
    the real store, so the `DuplicateOccurrence` itself is still raised by a
    genuine insert against a genuine claim.
    """

    def __init__(self, inner: InMemoryRunStore, blind: tuple[str, str]) -> None:
        self._inner = inner
        self._blind = blind

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def get_run_for_occurrence(self, schedule_id: str, scheduled_for: str) -> Run | None:
        if (schedule_id, scheduled_for) == self._blind:
            return None
        return await self._inner.get_run_for_occurrence(schedule_id, scheduled_for)


class _FailingOccurrenceLookup:
    """A run store whose occurrence index fails the store read, transiently.

    The resolution inside the duplicate-claim path is a store read like any
    other, and a store read can fail without lying: a connection drop, a
    command timeout. Only that lookup is intercepted; everything else
    delegates, so the `DuplicateOccurrence` is still raised by a genuine
    insert against a genuine claim.
    """

    def __init__(self, inner: InMemoryRunStore, failing: tuple[str, str]) -> None:
        self._inner = inner
        self._failing = failing

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def get_run_for_occurrence(self, schedule_id: str, scheduled_for: str) -> Run | None:
        if (schedule_id, scheduled_for) == self._failing:
            raise RuntimeError("synthetic store outage resolving the occurrence")
        return await self._inner.get_run_for_occurrence(schedule_id, scheduled_for)


class TestProvenance:
    async def test_the_run_names_the_schedule_that_fired_it(self, harness) -> None:
        """#46's "provenance retained **on the Run**", which is the whole point.
        It used to be retained beside it, as an audit line."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        result = await admitter.admit_due(schedule, now=NOON)

        assert len(result.run_ids) == 1
        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.provenance[ADMISSION_SOURCE] == SCHEDULE_SOURCE
        assert run.provenance[SCHEDULE_ID_KEY] == schedule.schedule_id
        # Named, not implied: an admitter that only ever produced recurring
        # Runs had no way to say so, and a consumer could not tell a nominal
        # occurrence from a manual one except by guessing from which keys were
        # absent (#1120).
        assert run.provenance[SCHEDULE_TRIGGER_KEY] == SCHEDULE_TRIGGER_RECURRING

    async def test_the_nominal_fire_time_is_recorded_not_the_tick(self, harness) -> None:
        """A Run that started late is still attributable to the occurrence it
        belongs to. `scheduled_for` reached the audit detail and stopped."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        # Noticed five minutes after the occurrence was due.
        noticed = NOON + timedelta(minutes=5)

        result = await admitter.admit_due(schedule, now=noticed)

        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.provenance[SCHEDULED_FOR_KEY] == NOON.isoformat()

    async def test_a_backfill_is_marked_as_a_catch_up(self, harness) -> None:
        """`FireDecision` has always drawn this distinction and it was dropped
        on the floor. Afterwards a backfill and an on-time fire were
        indistinguishable, and they mean different things.

        The boundary is one minute — the finest cadence cron expresses — so the
        noon occurrence, noticed half an hour late, is a backfill. Half an hour
        rather than a full one: the catch-up window is an hour wide, and an
        occurrence outside it is dropped as stale instead of backfilled.
        """
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        result = await admitter.admit_due(schedule, now=NOON + timedelta(minutes=30))

        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.provenance[SCHEDULE_CATCHUP_KEY] is True

    async def test_an_on_time_fire_is_not(self, harness) -> None:
        """Evaluated at the occurrence itself, so nothing was missed."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        result = await admitter.admit_due(schedule, now=NOON)

        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.provenance[SCHEDULE_CATCHUP_KEY] is False


class TestRequestCorrelation:
    """`admit_due` is the actual production scheduling path: the tick loop's
    `_evaluate_schedule` reaches this whenever a canonical admitter is
    configured, bypassing `_ScheduleRunner._fire_schedule` entirely (#1063).
    Every occurrence it admits must still carry its own correlation root."""

    async def test_an_admitted_occurrence_carries_its_own_request_id(self, harness) -> None:
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        result = await admitter.admit_due(schedule, now=NOON)

        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.provenance.get(REQUEST_ID_KEY)

    async def test_admitting_directly_with_no_context_omits_the_key(self, harness) -> None:
        """`_admit_one` only ever runs inside `admit_due`'s own
        `detached_execution_context()`, which always has a request_id bound
        -- but the method itself must not assume that; called with nothing
        bound (as it would be if some future caller admitted directly), the
        key is absent rather than blank, same discipline as `schedule_inputs`."""
        from maistro.graph.templates import require_template
        from maistro.scheduling.engine import FireDecision

        admitter, runs, templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        template = await require_template(templates, TEMPLATE_ID)

        run_id = await admitter._admit_one(
            schedule, template, FireDecision(scheduled_for=NOON, catchup=False)
        )

        run = await runs.get_run(run_id)
        assert run is not None
        assert REQUEST_ID_KEY not in run.provenance

    async def test_it_does_not_leak_a_stray_ambient_context(self, harness) -> None:
        """The tick loop shares an event loop with whatever else is running;
        an unrelated Attempt's ids left bound on this tick must not become
        this Run's correlation root."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        with bind_execution_context(run_id="stray-run", request_id="stray-request"):
            result = await admitter.admit_due(schedule, now=NOON)

        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.provenance[REQUEST_ID_KEY] != "stray-request"
        assert "run_id" not in run.provenance or run.provenance.get("run_id") != "stray-run"

    async def test_each_occurrence_in_a_catch_up_batch_gets_its_own_id(self, harness) -> None:
        """A backfill after downtime admits several occurrences in one
        `admit_due` call -- each is an independent scheduled invocation and
        must not share a correlation root with its siblings."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            cron="0 * * * *",
            last_fired_at=NOON - timedelta(hours=3),
            catchup_window_seconds=6 * 3600.0,
            overlap_policy=OverlapPolicy.ALLOW,
        )

        result = await admitter.admit_due(schedule, now=NOON)

        assert len(result.run_ids) > 1
        ids = set()
        for run_id in result.run_ids:
            run = await runs.get_run(run_id)
            assert run is not None
            ids.add(run.provenance.get(REQUEST_ID_KEY))
        assert len(ids) == len(result.run_ids)
        assert all(ids)


class TestTheCursor:
    async def test_last_run_id_resolves_in_the_run_store(self, harness) -> None:
        """schedule → its Run, the direction that did not exist. `last_run_id`
        was never written, so you could go Run → audit → schedule and not back."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == result.run_ids[-1]
        assert await runs.get_run(stored.last_run_id) is not None

    async def test_duplicate_claim_reconciles_the_winning_run_id(self, harness) -> None:
        """A crash after admission must not leave overlap checks blind.

        Resetting the schedule projection to its pre-fire snapshot models the
        process dying before `record_fire`; the Run claim remains canonical.
        """
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        first = await admitter.admit_due(schedule, now=NOON)
        winning_run_id = first.run_ids[0]
        # Reset the stored row to its pre-fire snapshot through the store API.
        # A `put` of the stale definition would not do it: `_merged` keeps an
        # existing row's cursors (#1199), so the reset was a no-op and the
        # assertion below could not fail. Deleting and re-filing the
        # definition is what models the process dying between the Run's
        # creation and `record_fire`: the claim remains, the linkage is gone.
        assert await schedules.delete(schedule.schedule_id) is True
        await schedules.put(schedule)

        recovered = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert recovered.run_ids == ()
        assert recovered.already_fired == (NOON,)
        assert stored is not None
        assert stored.last_run_id == winning_run_id
        winner = await runs.get_run_for_occurrence(schedule.schedule_id, NOON.isoformat())
        assert winner is not None and winner.run_id == winning_run_id

    async def test_terminal_duplicate_winner_stays_linked_but_does_not_block_next_fire(
        self, harness
    ) -> None:
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        first = await admitter.admit_due(schedule, now=NOON)
        winning_run_id = first.run_ids[0]
        await runs.transition_run(winning_run_id, RunStatus.CANCELLED)
        # The same real reset as above: `put` alone would have kept the stored
        # cursors, and `last_run_id == winning_run_id` would then pass without
        # the recovered write ever being exercised.
        assert await schedules.delete(schedule.schedule_id) is True
        await schedules.put(schedule)

        recovered = await admitter.admit_due(schedule, now=NOON)
        stored = await schedules.get(schedule.schedule_id)
        assert recovered.run_ids == ()
        assert stored is not None and stored.last_run_id == winning_run_id

        later = await admitter.admit_due(stored, now=NOON + timedelta(hours=1))

        assert len(later.run_ids) == 1
        assert later.run_ids[0] != winning_run_id

    async def test_duplicate_claim_with_an_unresolvable_winner_stops_the_batch(
        self, harness
    ) -> None:
        """A claim the occurrence index cannot resolve is torn state, not overlap.

        The admitter may carry a duplicate occurrence's winner into the cursor
        only when it can name the Run that won. A winner that resolves to
        nothing means the claim index and the Runs have come apart; recording
        it would point `last_run_id` at nothing and leave every later overlap
        check consulting a linkage nobody can answer. So the batch stops with
        the failure recorded and the cursor exactly where it was.
        """
        admitter, runs, templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        first = await admitter.admit_due(schedule, now=NOON)
        assert first.run_ids
        # `put` keeps an existing row's fire cursors, so the store still holds
        # the first process's linkage. That is exactly the state the failed
        # batch must leave untouched.
        before = await schedules.get(schedule.schedule_id)
        assert before is not None
        assert before.last_run_id == first.run_ids[0]

        reconciling = ScheduleRunAdmitter(
            # Delegation satisfies the protocol at runtime; the checker only
            # sees the one intercepted method.
            _UnresolvableOccurrenceWinner(  # type: ignore[arg-type]
                runs, blind=(schedule.schedule_id, NOON.isoformat())
            ),
            templates,
            schedules,
        )

        recovered = await reconciling.admit_due(schedule, now=NOON)

        assert recovered.run_ids == ()
        assert recovered.already_fired == ()
        assert len(recovered.failures) == 1
        assert isinstance(recovered.failures[0], RunIntegrityError)
        assert "no resolvable canonical Run" in str(recovered.failures[0])
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == before.last_run_id
        assert stored.last_fired_at == before.last_fired_at
        assert stored.runs_so_far == before.runs_so_far

    async def test_a_transient_lookup_failure_stops_the_batch_but_still_records(
        self, harness
    ) -> None:
        """Resolving a duplicate's winner is a store read, so it can fail
        transiently — and that failure must not escape `admit_due`.

        Escaping would skip `record_fire` for occurrences this batch already
        admitted: their Runs exist, their claims are held, and the cursor
        write that tells the next tick so would never land. The failure is
        recorded and the batch stops like any other per-occurrence error,
        while the advance that the admitted occurrences have earned still
        happens.
        """
        admitter, runs, templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            last_fired_at=NOON - timedelta(hours=2),
            catchup_window_seconds=6 * 3600.0,
            overlap_policy=OverlapPolicy.ALLOW,
        )
        # A rival ticker claimed the 11:00 occurrence (the only one due at
        # NOON-1h) and advanced the stored cursor over it. This batch's caller
        # still holds a replica snapshot from before that advance, so it
        # re-enumerates the unclaimed 10:00, the claimed 11:00, and 12:00 —
        # the sequence a replica that missed the rival's write really sees.
        rival = await admitter.admit_due(schedule, now=NOON - timedelta(hours=1))
        assert len(rival.run_ids) == 1
        replica = schedule.model_copy(update={"last_fired_at": NOON - timedelta(hours=3)})

        reconciling = ScheduleRunAdmitter(
            _FailingOccurrenceLookup(  # type: ignore[arg-type]
                runs, failing=(schedule.schedule_id, (NOON - timedelta(hours=1)).isoformat())
            ),
            templates,
            schedules,
        )

        result = await reconciling.admit_due(replica, now=NOON)

        # The failure is reported, not raised.
        assert len(result.failures) == 1
        assert isinstance(result.failures[0], RuntimeError)
        # The occurrence admitted before the failure reached `record_fire`.
        assert len(result.run_ids) == 1
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        # The 10:00 fire really landed — and the linkage stays with the
        # newest consumed occurrence (the rival's 11:00): `_advance` moves
        # the counters for the stale occurrence while its older cursors
        # cannot regress what the newer one recorded.
        assert stored.runs_so_far == 2
        assert stored.last_fired_at == NOON - timedelta(hours=1)
        assert stored.last_run_id == rival.run_ids[0]

    async def test_the_cursor_does_not_move_when_no_run_was_created(self, harness) -> None:
        """The ordering the issue names: advancing first would skip an
        occurrence that never ran, permanently and silently."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, graph_template_id="never-registered")
        before = await schedules.get(schedule.schedule_id)

        result = await admitter.admit_due(schedule, now=NOON)

        after = await schedules.get(schedule.schedule_id)
        assert result.run_ids == ()
        assert result.failures
        assert isinstance(result.failures[0], GraphTemplateNotFound)
        assert after is not None and before is not None
        assert after.last_fired_at == before.last_fired_at
        assert after.runs_so_far == before.runs_so_far

    async def test_an_unresolvable_template_is_retryable_once_it_is_registered(
        self, harness
    ) -> None:
        """Which is what leaving the cursor alone buys. The old behaviour
        stamped `last_run` and returned early, so the occurrence was gone."""
        admitter, _runs, templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, graph_template_id="late")

        first = await admitter.admit_due(schedule, now=NOON)
        assert first.run_ids == ()

        await templates.put(
            GraphTemplate(
                template_id="late",
                workspace_id="w1",
                name="late",
                nodes=[Node(node_id="n1", node_type="agent", name="a")],
            )
        )
        again = await admitter.admit_due(await schedules.get(schedule.schedule_id), now=NOON)

        assert len(again.run_ids) == 1

    async def test_nothing_due_records_no_fire(self, harness) -> None:
        """`next_due_at` still moved and the caller wants it — and recording
        it must not stamp `last_fired_at` for a fire that did not happen
        (#1199 writes the due cursor alone)."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, last_fired_at=NOON)
        before = await schedules.get(schedule.schedule_id)

        result = await admitter.admit_due(schedule, now=NOON)

        after = await schedules.get(schedule.schedule_id)
        assert result.run_ids == ()
        assert result.next_due_at is not None
        assert after is not None and before is not None
        assert after.last_fired_at == before.last_fired_at
        assert after.runs_so_far == before.runs_so_far
        assert after.next_due_at == result.next_due_at


class TestTheDueCursorIsRecordedWithoutAFire:
    """The first defect #1199 names in the canonical store.

    `ScheduleStore.due()` selects on `next_due_at`, and a missing cursor is
    due by contract (an unknown cursor must be evaluated). An evaluation that
    fired nothing computed the next occurrence and returned it to the caller
    without persisting it — so a schedule whose first occurrence is next week
    was handed to the admitter on every tick until then, and a tick reading
    `due()` could never tell it apart from real work.
    """

    async def test_a_future_schedule_stops_being_due_after_its_first_evaluation(
        self, harness
    ) -> None:
        admitter, _runs, _templates, schedules, project_id = harness
        # Created just after the hour, never fired: its first occurrence is
        # 13:00, and the first tick to look at it comes at 12:00:30.
        tick = NOON + timedelta(seconds=30)
        schedule = await _schedule(
            schedules,
            project_id,
            created_at=NOON + timedelta(seconds=1),
            last_fired_at=None,
            next_due_at=None,
        )
        assert [s.schedule_id for s in await schedules.due(now=tick)] == [schedule.schedule_id]

        result = await admitter.admit_due(schedule, now=tick)

        assert result.run_ids == () and result.skipped == ()
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.next_due_at == NOON + timedelta(hours=1)
        assert stored.last_fired_at is None
        assert stored.runs_so_far == 0
        assert stored.last_run_id is None
        # Not due again until the occurrence it recorded.
        assert await schedules.due(now=NOON + timedelta(minutes=59)) == []
        assert [s.schedule_id for s in await schedules.due(now=NOON + timedelta(hours=1))] == [
            schedule.schedule_id
        ]

    async def test_the_recorded_cursor_is_where_the_next_evaluation_fires(self, harness) -> None:
        """Recording the due cursor changes when the schedule is *looked at*,
        never what it does: the occurrence still fires, once, on time."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            created_at=NOON + timedelta(seconds=1),
            last_fired_at=None,
            next_due_at=None,
        )
        await admitter.admit_due(schedule, now=NOON + timedelta(seconds=30))
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None and stored.next_due_at is not None

        later = await admitter.admit_due(stored, now=stored.next_due_at)

        assert len(later.run_ids) == 1
        run = await runs.get_run(later.run_ids[0])
        assert run is not None
        assert run.provenance[SCHEDULED_FOR_KEY] == (NOON + timedelta(hours=1)).isoformat()

    async def test_an_unchanged_cursor_is_not_rewritten_every_tick(self, harness) -> None:
        """Idle schedules are most schedules; an evaluation that learned
        nothing new must not cost a write."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules, project_id, last_fired_at=NOON, next_due_at=NOON + timedelta(hours=1)
        )
        before = await schedules.get(schedule.schedule_id)
        assert before is not None

        await admitter.admit_due(schedule, now=NOON + timedelta(minutes=1))

        after = await schedules.get(schedule.schedule_id)
        assert after is not None
        assert after.updated_at == before.updated_at

    async def test_a_buffered_occurrence_keeps_the_schedule_due(self, harness) -> None:
        """BUFFER_ONE holds an occurrence back while a Run is active, to run it
        once that Run finishes. Advancing the due cursor past it would hide
        the schedule from `due()` until the occurrence *after* the one it
        still owes — a deferral of one whole period, not "afterwards"."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            overlap_policy=OverlapPolicy.BUFFER_ONE,
            last_fired_at=NOON - timedelta(hours=1),
            next_due_at=NOON,
        )

        result = await admitter.admit_due(schedule, now=NOON, active_run=True)

        assert [skip.reason for skip in result.skipped] == [SkipReason.BUFFERED]
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.next_due_at == NOON
        assert stored.last_fired_at == NOON - timedelta(hours=1)
        assert [s.schedule_id for s in await schedules.due(now=NOON)] == [schedule.schedule_id]

    async def test_a_fire_beside_a_buffered_occurrence_keeps_the_schedule_due(
        self, harness
    ) -> None:
        """The same rule on the firing path: one occurrence ran and the next
        is held, so the schedule is still owed work and stays due."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            overlap_policy=OverlapPolicy.BUFFER_ONE,
            # Two occurrences owed (11:00 and 12:00), both inside the window.
            catchup_window_seconds=4 * 3600,
            last_fired_at=NOON - timedelta(hours=2),
            next_due_at=NOON - timedelta(hours=1),
        )

        result = await admitter.admit_due(schedule, now=NOON)

        assert len(result.run_ids) == 1
        assert [skip.reason for skip in result.skipped] == [SkipReason.BUFFERED]
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_fired_at == NOON - timedelta(hours=1)
        assert stored.next_due_at == NOON - timedelta(hours=1)
        assert [s.schedule_id for s in await schedules.due(now=NOON)] == [schedule.schedule_id]

    async def test_a_disabled_schedule_records_nothing(self, harness) -> None:
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, enabled=False, next_due_at=None)
        before = await schedules.get(schedule.schedule_id)
        assert before is not None

        await admitter.admit_due(schedule, now=NOON)

        after = await schedules.get(schedule.schedule_id)
        assert after is not None and after.updated_at == before.updated_at


class TestBoundedRecurrence:
    async def test_reaching_max_runs_disables_in_the_same_write(self, harness) -> None:
        """`max_runs` was unreachable through the product surface: the hive loop
        constructed its projected Schedule without it."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=1, runs_so_far=0)

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert len(result.run_ids) == 1
        assert result.disabled is True
        assert stored is not None
        assert stored.enabled is False
        assert stored.next_due_at is None

    async def test_a_schedule_short_of_its_limit_stays_enabled(self, harness) -> None:
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=5, runs_so_far=0)

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert result.disabled is False
        assert stored is not None
        assert stored.enabled is True
        assert stored.runs_so_far == len(result.run_ids)

    async def test_an_exhausted_schedule_fires_nothing(self, harness) -> None:
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=2, runs_so_far=2)

        result = await admitter.admit_due(schedule, now=NOON)

        assert result.run_ids == ()


class TestOverlap:
    async def test_skip_reports_its_reason_rather_than_firing(self, harness) -> None:
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.SKIP)

        result = await admitter.admit_due(schedule, now=NOON, active_run=True)

        assert result.run_ids == ()
        assert result.skipped
        assert result.skipped[0].reason is not None

    async def test_cancel_other_is_reported_for_the_caller_to_act_on(self, harness) -> None:
        """This admitter creates Runs and does not know which one is in flight.
        The caller tracking that is the one that can cancel it."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.CANCEL_OTHER)

        result = await admitter.admit_due(schedule, now=NOON, active_run=True)

        assert result.cancel_active_run is True


class TestDisabled:
    async def test_a_disabled_schedule_admits_nothing(self, harness) -> None:
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, enabled=False)

        result = await admitter.admit_due(schedule, now=NOON)

        assert result.run_ids == ()
        assert result.next_due_at is None


# ── what the cursor may and may not cross (Codex P1 x3, P2 x1 on #218) ──


class TestTheCursorNeverCrossesAnOwedOccurrence:
    """The batch cases the first version got wrong.

    `record_fire` moves the cursor past everything it covers, and the cursor is
    the lower bound of the next enumeration. So "advance only after the Runs
    exist" is necessary and not sufficient: *which* occurrences it advances past
    matters just as much, and a batch makes them differ.
    """

    async def test_a_failure_mid_batch_leaves_the_rest_owed(self, harness) -> None:
        """The earlier version collected the failure and kept going, then
        advanced past the whole batch — losing the failed occurrence
        permanently, which is the exact outcome this admitter exists to
        prevent."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            last_fired_at=NOON - timedelta(hours=4),
            catchup_window_seconds=6 * 3600.0,
            overlap_policy=OverlapPolicy.ALLOW,
        )

        calls = {"n": 0}
        original = admitter._admit_one

        async def _fail_on_the_second(schedule_, template_, fire_):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("run store refused")
            return await original(schedule_, template_, fire_)

        admitter._admit_one = _fail_on_the_second  # type: ignore[method-assign]

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert result.failures
        assert len(result.run_ids) == 1
        assert stored is not None
        # The cursor sits on the occurrence that succeeded, so the failed one
        # and everything after it are still owed.
        assert stored.last_fired_at < NOON
        assert stored.runs_so_far == 1

    async def test_the_cursor_is_the_occurrence_not_the_tick(self, harness) -> None:
        """`fired_at=now` would carry the cursor past occurrences the batch
        stopped short of, whatever the stopping rule was."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        noticed = NOON + timedelta(minutes=45)

        await admitter.admit_due(schedule, now=noticed)

        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_fired_at == NOON
        assert stored.last_fired_at != noticed


class TestSkipMeansDropNotDefer:
    """`OverlapPolicy.SKIP` is documented as "Drop the fire; the in-flight Run
    keeps going". Leaving the cursor behind made it *defer*: the occurrence came
    due again next tick and fired once the active Run finished.

    `SkipReason` already drew the line — BUFFERED and TRUNCATED say in as many
    words that their occurrence is still owed, and nothing else does.
    """

    async def test_an_overlap_skip_consumes_its_occurrence(self, harness) -> None:
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.SKIP)
        before = await schedules.get(schedule.schedule_id)

        result = await admitter.admit_due(schedule, now=NOON, active_run=True)

        after = await schedules.get(schedule.schedule_id)
        assert result.run_ids == ()
        assert after is not None and before is not None
        assert after.last_fired_at > before.last_fired_at

    async def test_a_dropped_occurrence_does_not_fire_on_the_next_tick(self, harness) -> None:
        """The property the cursor move buys, asserted end to end."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.SKIP)

        await admitter.admit_due(schedule, now=NOON, active_run=True)
        # The Run finished; the same nominal occurrence must not come back.
        again = await admitter.admit_due(
            await schedules.get(schedule.schedule_id), now=NOON, active_run=False
        )

        assert again.run_ids == ()

    async def test_a_consumed_skip_does_not_count_as_a_fire(self, harness) -> None:
        """It produced no Run, so `runs_so_far` must not move — otherwise a
        bounded schedule burns its `max_runs` on occurrences it dropped."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules, project_id, overlap_policy=OverlapPolicy.SKIP, max_runs=5
        )

        await admitter.admit_due(schedule, now=NOON, active_run=True)

        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.runs_so_far == 0
        assert stored.last_run_id is None


class TestScheduleInputs:
    async def test_a_configured_payload_reaches_the_run(self, harness) -> None:
        """`Schedule.inputs` was dropped, so a parameterized schedule produced
        a Run indistinguishable from one configured with nothing."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, inputs={"region": "eu-west", "depth": 3})

        result = await admitter.admit_due(schedule, now=NOON)

        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.provenance[SCHEDULE_INPUTS_KEY] == {"region": "eu-west", "depth": 3}

    async def test_no_inputs_records_no_key(self, harness) -> None:
        """Absent rather than an empty dict: a Run that never had inputs and one
        configured with `{}` are the same thing, and the shorter provenance is
        the honest one."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        result = await admitter.admit_due(schedule, now=NOON)

        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert SCHEDULE_INPUTS_KEY not in run.provenance


class TestTemplateResolutionIsPerBatch:
    async def test_a_missing_template_is_looked_up_once_for_the_whole_batch(self, harness) -> None:
        """A minutely schedule after an outage has hundreds of due occurrences.
        Resolving per occurrence turned one configuration error into hundreds of
        store round trips and log lines per tick — while the cursor stayed put,
        so the burst repeated on every poll."""
        admitter, _runs, templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            graph_template_id="never-registered",
            cron="* * * * *",
            last_fired_at=NOON - timedelta(minutes=30),
            catchup_window_seconds=3600.0,
        )

        lookups = {"n": 0}
        original = templates.get

        async def _counted(template_id, *, version=None):
            lookups["n"] += 1
            return await original(template_id, version=version)

        templates.get = _counted  # type: ignore[method-assign]

        result = await admitter.admit_due(schedule, now=NOON)

        assert result.run_ids == ()
        assert result.failures
        # One lookup for the batch, however many occurrences were due.
        assert lookups["n"] == 1


class TestOneRunPerFiring:
    """Exactly-once admission of an occurrence (#220, ADR-082426-82c7).

    The cursor was the only thing standing between one firing and two Runs, and
    a cursor is a high-water mark rather than the identity of an occurrence.
    These are the admitter's half; the store's half — the claim itself, and the
    concurrent race — is in `runs/test_spine_conformance.py`, on all three
    backends.
    """

    async def test_a_crash_before_the_cursor_moved_does_not_refire(self, harness) -> None:
        """The known cost of create-then-advance, now paid. Re-running the
        admitter with the cursor exactly where it was is what the next tick
        after such a crash does."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        first = await admitter.admit_due(schedule, now=NOON)
        assert len(first.run_ids) == 1

        # The same Schedule object: its `last_fired_at` is the pre-fire value,
        # which is precisely the state a crash between the two writes leaves.
        again = await admitter.admit_due(schedule, now=NOON)

        assert again.run_ids == ()
        assert len(again.already_fired) == 1
        scheduled = [
            run
            for run in [await runs.get_run(run_id) for run_id in first.run_ids]
            if run is not None
        ]
        assert len(scheduled) == 1

    async def test_a_duplicate_does_not_stop_the_batch(self, harness) -> None:
        """The one place a `break` on first failure is wrong. Nothing is owed
        for an occurrence that already fired, so stopping would re-enumerate it
        on every tick from here on."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            last_fired_at=NOON - timedelta(hours=3),
            catchup_window_seconds=6 * 3600.0,
            overlap_policy=OverlapPolicy.ALLOW,
        )
        # A rival ticker got the *first* of the three due occurrences and then
        # stopped. Its cursor write does not matter here: this admitter is
        # driving the Schedule object it had already read.
        first_only = await admitter.admit_due(schedule, now=NOON - timedelta(hours=2))
        assert len(first_only.run_ids) == 1

        result = await admitter.admit_due(schedule, now=NOON)

        assert len(result.already_fired) == 1
        assert len(result.run_ids) == 2
        assert result.failures == ()

    async def test_the_cursor_passes_an_occurrence_someone_else_fired(self, harness) -> None:
        """It fired. Leaving the cursor short of it would re-enumerate a firing
        that has already happened, forever."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        await admitter.admit_due(schedule, now=NOON)
        before = await schedules.get(schedule.schedule_id)

        await admitter.admit_due(schedule, now=NOON)

        after = await schedules.get(schedule.schedule_id)
        assert after is not None and before is not None
        assert after.last_fired_at == before.last_fired_at

    async def test_a_duplicate_does_not_count_toward_max_runs(self, harness) -> None:
        """`fires` feeds `runs_so_far`. Both tickers counting one firing would
        exhaust a schedule at half the occurrences it was configured for."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=4)
        await admitter.admit_due(schedule, now=NOON)
        after_first = await schedules.get(schedule.schedule_id)

        await admitter.admit_due(schedule, now=NOON)

        after_second = await schedules.get(schedule.schedule_id)
        assert after_first is not None and after_second is not None
        assert after_first.runs_so_far == 1
        assert after_second.runs_so_far == 1

    async def test_last_run_id_survives_a_batch_that_admitted_nothing_new(self, harness) -> None:
        """`record_fire(run_id=None)` keeps the existing pointer. Clearing it,
        or pointing it at an older Run of ours, would both be less true than
        leaving it where the admitter that created the Run put it."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        first = await admitter.admit_due(schedule, now=NOON)

        await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == first.run_ids[-1]

    async def test_a_failure_on_the_first_occurrence_consumes_nothing(self, harness) -> None:
        """`consumed` gates the cursor write. When the very first occurrence
        fails there is nothing to advance past, and stamping `last_fired_at`
        anyway would skip a firing that never happened."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            last_fired_at=NOON - timedelta(hours=4),
            catchup_window_seconds=6 * 3600.0,
            overlap_policy=OverlapPolicy.ALLOW,
        )
        before = await schedules.get(schedule.schedule_id)

        async def _always_fail(schedule_, template_, fire_):
            raise RuntimeError("run store refused")

        admitter._admit_one = _always_fail  # type: ignore[method-assign]

        result = await admitter.admit_due(schedule, now=NOON)

        after = await schedules.get(schedule.schedule_id)
        assert result.run_ids == ()
        assert result.already_fired == ()
        assert len(result.failures) == 1
        assert after is not None and before is not None
        assert after.last_fired_at == before.last_fired_at
        assert after.runs_so_far == before.runs_so_far


async def _crashed_before_record_fire(harness, schedule: Schedule, when: datetime) -> str:
    """Ticker A's half of the #1059 sequence: the Run for `when` exists and
    the cursor was never stamped, which is exactly what dying between
    `create_run` and `record_fire` leaves behind."""
    admitter, _runs, templates, _schedules, _project_id = harness
    template = await templates.get(TEMPLATE_ID)
    assert template is not None
    return await admitter._admit_one(schedule, template, FireDecision(scheduled_for=when))


class TestRecoverySeesTheRunStoreBeforeThePolicy:
    """The #1059 review's findings on the linkage change.

    A crashed winner is a Run with no pointer to it. The overlap policy used
    to be applied from the caller's stale `active_run`, so under CANCEL_OTHER
    the crashed occurrence fell into `skipped` — never reaching the duplicate
    handler — while the newer occurrence was admitted beside its live Run with
    no cancellation asked for.

    Counting note (supersession of #1282's store contract): the branch made
    the store dedupe fires per occurrence, so a recovered winner could be
    counted exactly once by whoever consumed it. Develop kept `fires: int` as
    a delta, so the reactive rule stands — the winner's ticker counts, a
    claimant that finds the Run never does. These tests assert develop's
    reachable behaviour: linkage and policy judgement are exact; recovered
    counts are only exact for the pre-horizon walk (the horizon class below).
    """

    async def test_cancel_other_finds_the_crashed_winner_and_asks_for_its_cancellation(
        self, harness
    ) -> None:
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            overlap_policy=OverlapPolicy.CANCEL_OTHER,
            # Wide enough that the crashed occurrence is still enumerated an
            # hour later, beside the next one.
            catchup_window_seconds=4 * 3600.0,
        )
        winner = await _crashed_before_record_fire(harness, schedule, NOON)
        assert (await schedules.get(schedule.schedule_id)).last_run_id is None

        later = await admitter.admit_due(schedule, now=NOON + timedelta(hours=1), active_run=False)

        assert len(later.run_ids) == 1
        assert later.already_fired == (NOON,)
        assert later.cancel_active_run is True, "the live crashed winner is the in-flight Run"
        assert later.active_run_id == winner
        assert all(skip.reason is SkipReason.OVERLAP for skip in later.skipped)
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == later.run_ids[0], "the pointer follows the newest occurrence"
        assert stored.last_fired_at == NOON + timedelta(hours=1)
        assert stored.runs_so_far == 1, "the new fire counts; the winner's ticker counted NOON"
        assert await runs.get_run(winner) is not None

    async def test_skip_defers_to_the_crashed_winner_the_pointer_never_named(self, harness) -> None:
        """`active_run=False` from a stale pointer must not let SKIP run the
        next occurrence beside the crashed one."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            overlap_policy=OverlapPolicy.SKIP,
            catchup_window_seconds=4 * 3600.0,
        )
        winner = await _crashed_before_record_fire(harness, schedule, NOON)

        later = await admitter.admit_due(schedule, now=NOON + timedelta(hours=1), active_run=False)

        assert later.run_ids == ()
        assert later.already_fired == (NOON,)
        assert later.cancel_active_run is False
        assert {skip.reason for skip in later.skipped} == {SkipReason.OVERLAP}
        assert later.active_run_id == winner
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == winner
        assert stored.last_fired_at == NOON + timedelta(hours=1), "the overlap skip is consumed"
        # The winner's firing stays uncounted here: NOON sat inside the
        # enumerated window, so the reactive rule owns it and the delta
        # contract never saw a count from the dead ticker. Exact recovery
        # counting is the pre-horizon walk's (the horizon class below).
        assert stored.runs_so_far == 0

    async def test_two_tickers_consuming_one_occurrence_count_it_once(self, harness) -> None:
        """The refused ticker consumes the winner's occurrence without
        counting it, so the firing lands in `runs_so_far` exactly once —
        written by whichever ticker won the claim."""
        admitter, runs, templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=2)
        rival = ScheduleRunAdmitter(runs, templates, schedules)

        await asyncio.gather(
            admitter.admit_due(schedule, now=NOON), rival.admit_due(schedule, now=NOON)
        )

        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.runs_so_far == 1
        assert stored.enabled is True


class TestRecoveryBeyondTheCatchUpHorizon:
    """A winner that crashed before the catch-up horizon is still recovered.

    `evaluate()` enumerates from the horizon forward, so a ticker that died
    mid-fire and stayed down longer than the window leaves a Run at an
    occurrence no later evaluation looks at: never linked, never counted, and
    invisible to the overlap policy. The admitter walks the claims forward
    from the cursor instead — one lookup per contiguous crashed Run, one on
    the common path — up to where the enumeration begins (#1059 review).

    These claims are the provably-unrecorded ones: recording an occurrence
    moves the cursor onto it, and these sit behind the cursor — so, unlike
    claims on enumerated occurrences, the walk's findings count toward
    `fires` here, once, under develop's delta contract.
    """

    async def test_a_winner_one_cadence_back_is_recovered_with_the_default_window(
        self, harness
    ) -> None:
        """Hourly schedule, one-hour window, next tick a full hour later: the
        crashed occurrence is exactly at the horizon and would not be
        enumerated."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.SKIP)
        winner = await _crashed_before_record_fire(harness, schedule, NOON)

        later = await admitter.admit_due(schedule, now=NOON + timedelta(hours=1), active_run=False)

        assert later.run_ids == ()
        assert later.already_fired == (NOON,)
        assert later.active_run_id == winner
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == winner
        assert stored.runs_so_far == 1

    async def test_skip_defers_to_a_winner_that_crashed_before_the_horizon(self, harness) -> None:
        """Down for three hours: the NOON winner is two occurrences behind the
        horizon and still live, so SKIP must not fire 15:00 beside it."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.SKIP)
        winner = await _crashed_before_record_fire(harness, schedule, NOON)

        later = await admitter.admit_due(schedule, now=NOON + timedelta(hours=3), active_run=False)

        assert later.run_ids == ()
        assert later.already_fired == (NOON,)
        assert later.active_run_id == winner
        assert SkipReason.OVERLAP in {skip.reason for skip in later.skipped}
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == winner
        assert stored.last_fired_at == NOON + timedelta(hours=3)
        assert stored.runs_so_far == 1, "the crashed firing is counted once"

    async def test_cancel_other_cancels_a_winner_that_crashed_before_the_horizon(
        self, harness
    ) -> None:
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.CANCEL_OTHER)
        winner = await _crashed_before_record_fire(harness, schedule, NOON)

        later = await admitter.admit_due(schedule, now=NOON + timedelta(hours=3), active_run=False)

        assert len(later.run_ids) == 1
        assert later.cancel_active_run is True
        assert later.active_run_id == winner
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == later.run_ids[0]
        assert stored.runs_so_far == 2

    async def test_a_batch_of_crashed_winners_is_recovered_contiguously(self, harness) -> None:
        """A ticker that admitted 12:00 and 13:00 in one batch and died before
        recording leaves two Runs after the cursor; both are found."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.ALLOW)
        first = await _crashed_before_record_fire(harness, schedule, NOON)
        second = await _crashed_before_record_fire(harness, schedule, NOON + timedelta(hours=1))

        later = await admitter.admit_due(schedule, now=NOON + timedelta(hours=4))

        assert later.already_fired == (NOON, NOON + timedelta(hours=1))
        assert len(later.run_ids) == 1
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.runs_so_far == 3
        assert stored.last_run_id == later.run_ids[0]
        for run_id in (first, second):
            assert await runs.get_run(run_id) is not None, "recovered, not replaced"

    async def test_the_walk_stops_at_the_first_occurrence_without_a_run(self, harness) -> None:
        """Bounded by the crashed batch, not by the outage: after five hours
        down, the lookups are the crashed occurrence, the empty one after it,
        and the one occurrence the window still enumerates."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.ALLOW)
        await _crashed_before_record_fire(harness, schedule, NOON)
        looked_up: list[str] = []
        real_lookup = runs.get_run_for_occurrence

        async def _counted(schedule_id: str, scheduled_for: str):
            looked_up.append(scheduled_for)
            return await real_lookup(schedule_id, scheduled_for)

        runs.get_run_for_occurrence = _counted  # type: ignore[method-assign]

        later = await admitter.admit_due(schedule, now=NOON + timedelta(hours=5))

        assert later.already_fired == (NOON,)
        assert sorted(looked_up) == sorted(
            [
                (NOON + timedelta(hours=5)).isoformat(),
                NOON.isoformat(),
                (NOON + timedelta(hours=1)).isoformat(),
            ]
        )

    async def test_an_idle_tick_costs_one_lookup_at_most(self, harness) -> None:
        """The common path: nothing crashed, nothing due. The walk probes the
        first occurrence after the cursor, finds no Run, and stops."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules, project_id, last_fired_at=NOON, next_due_at=NOON + timedelta(hours=1)
        )
        looked_up: list[str] = []
        real_lookup = runs.get_run_for_occurrence

        async def _counted(schedule_id: str, scheduled_for: str):
            looked_up.append(scheduled_for)
            return await real_lookup(schedule_id, scheduled_for)

        runs.get_run_for_occurrence = _counted  # type: ignore[method-assign]

        await admitter.admit_due(schedule, now=NOON + timedelta(minutes=1))

        assert looked_up == []


class TestAdmissionState:
    @pytest.mark.ac("ADR-082826-b601/AC-5")
    async def test_the_run_is_queued_in_the_same_insert(self, harness) -> None:
        """A schedule Run's admission is its submission (#251).

        No caller holds a receipt that will queue it later, so a Run left
        CREATED here was admitted work nobody would ever execute — and the
        consumer tick deliberately never claims CREATED.
        """
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        result = await admitter.admit_due(schedule, now=NOON)

        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.status is RunStatus.QUEUED


class TestManualFire:
    """`admit_due(manual=True)` (#1119): the recurring authority, one occurrence wide.

    A product "run this schedule now" is not an occurrence the cron
    enumerated, so `evaluate()` has nothing to say about it — but everything
    after that decision must be the recurring path's, or the same persisted
    schedule stays reachable through two different firing semantics.
    """

    async def test_a_manual_fire_is_one_run_with_the_schedule_on_it(self, harness) -> None:
        """Provenance, claim, and cursor behave exactly as `admit_due`'s."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        now = NOON + timedelta(minutes=7)

        result = await admitter.admit_due(schedule, now=now, manual=True)

        assert len(result.run_ids) == 1
        assert not result.failures and result.already_fired == ()
        run = await runs.get_run(result.run_ids[0])
        assert run is not None
        assert run.status is RunStatus.QUEUED
        assert run.workspace_id == "w1"
        assert run.project_id == project_id
        assert run.provenance[ADMISSION_SOURCE] == SCHEDULE_SOURCE
        assert run.provenance[SCHEDULE_ID_KEY] == schedule.schedule_id
        assert run.provenance[SCHEDULED_FOR_KEY] == now.isoformat()
        # The caller asked for a fire *now*; it is on-time by definition.
        assert run.provenance[SCHEDULE_CATCHUP_KEY] is False

        recorded = await schedules.get(schedule.schedule_id)
        assert recorded is not None
        assert recorded.last_run_id == run.run_id
        assert recorded.runs_so_far == 1
        # The recurrence cursor is the cron's, and a manual fire is not one of
        # its occurrences: it stays exactly where the schedule left it.
        assert recorded.last_fired_at == schedule.last_fired_at
        assert recorded.next_due_at == schedule.next_due_at

    async def test_a_manual_fire_does_not_carry_the_cursor_past_an_owed_occurrence(
        self, harness
    ) -> None:
        """Cursor at 11:00, the 12:00 occurrence due, a manual fire at 12:00:30.

        Stamping the fire on `last_fired_at` would start the next evaluation
        after 12:00:30 and silently drop 12:00, although the manual Run claims
        a different instant. The tick that follows must still admit 12:00.
        """
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules, project_id, last_fired_at=NOON - timedelta(hours=1), next_due_at=NOON
        )
        moment = NOON + timedelta(seconds=30)

        manual = await admitter.admit_due(schedule, now=moment, manual=True)
        assert len(manual.run_ids) == 1
        current = await schedules.get(schedule.schedule_id)
        assert current is not None
        assert current.last_fired_at == NOON - timedelta(hours=1)
        assert current.next_due_at == NOON

        ticked = await admitter.admit_due(current, now=moment)

        assert len(ticked.run_ids) == 1
        owed = await runs.get_run(ticked.run_ids[0])
        assert owed is not None
        assert owed.provenance[SCHEDULED_FOR_KEY] == NOON.isoformat()
        recorded = await schedules.get(schedule.schedule_id)
        assert recorded is not None
        assert recorded.last_fired_at == NOON
        assert recorded.runs_so_far == 2

    async def test_concurrent_manual_fires_cannot_exceed_max_runs(
        self, harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two requests on the last run, both past the snapshot check: one Run.

        The quota is claimed before the Run exists, under the store's lock, so
        the second caller is refused rather than counted after the fact.
        """
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=1)
        release = asyncio.Event()
        real_create = runs.create_run

        async def _slow_create(*args: object, **kwargs: object) -> object:
            await release.wait()
            return await real_create(*args, **kwargs)

        monkeypatch.setattr(runs, "create_run", _slow_create)
        first = asyncio.create_task(admitter.admit_due(schedule, now=NOON, manual=True))
        second = asyncio.create_task(
            admitter.admit_due(schedule, now=NOON + timedelta(seconds=1), manual=True)
        )
        await asyncio.sleep(0)
        release.set()
        outcomes = await asyncio.gather(first, second, return_exceptions=True)

        admitted = [item for item in outcomes if isinstance(item, ScheduleAdmission)]
        refused = [item for item in outcomes if isinstance(item, ManualFireRefused)]
        assert len(admitted) == 1 and len(refused) == 1
        assert len(runs._runs) == 1  # type: ignore[attr-defined]
        recorded = await schedules.get(schedule.schedule_id)
        assert recorded is not None
        assert recorded.runs_so_far == 1
        assert recorded.enabled is False

    async def test_a_run_that_exists_is_counted_even_if_recording_it_fails(
        self, harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The slot is claimed before the Run, so a failure after creation
        cannot leave a Run the count does not admit to: the next request is
        refused instead of duplicating the work."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=1)
        real_settle = schedules.settle_fire

        async def _settle_fails(schedule_id: str, reservation: object, *, run_id: str | None):
            if run_id is not None:
                raise RuntimeError("synthetic store outage after the Run exists")
            return await real_settle(schedule_id, reservation, run_id=run_id)

        monkeypatch.setattr(schedules, "settle_fire", _settle_fails)
        with pytest.raises(RuntimeError, match="after the Run exists"):
            await admitter.admit_due(schedule, now=NOON, manual=True)

        assert len(runs._runs) == 1  # type: ignore[attr-defined]
        recorded = await schedules.get(schedule.schedule_id)
        assert recorded is not None
        assert recorded.runs_so_far == 1
        assert recorded.last_run_id is None, "the pointer is what the outage lost"
        monkeypatch.setattr(schedules, "settle_fire", real_settle)
        with pytest.raises(ManualFireRefused):
            await admitter.admit_due(recorded, now=NOON + timedelta(minutes=1), manual=True)
        assert len(runs._runs) == 1  # type: ignore[attr-defined]

    async def test_a_manual_fire_counts_against_max_runs_and_disables(self, harness) -> None:
        """A manual fire is a fire: it spends the bound and disables.

        The compatibility path this replaces counted the fire but only on its
        own cursor; the bound must bind on the canonical one either way.
        """
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=2)

        first = await admitter.admit_due(schedule, now=NOON, manual=True)
        assert not first.disabled
        # The caller owes the admitter a current cursor — the hive layer
        # re-reads the definition before every fire, as `_definition_for` does
        # for the tick. Firing again on the stale pre-fire copy would undercount.
        current = await schedules.get(schedule.schedule_id)
        assert current is not None
        second = await admitter.admit_due(current, now=NOON + timedelta(hours=1), manual=True)
        assert second.disabled

        recorded = await schedules.get(schedule.schedule_id)
        assert recorded is not None
        assert recorded.runs_so_far == 2
        assert recorded.enabled is False
        assert recorded.next_due_at is None

    async def test_an_exhausted_schedule_refuses_and_changes_nothing(self, harness) -> None:
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=1, runs_so_far=1)
        before = await schedules.get(schedule.schedule_id)

        with pytest.raises(ManualFireRefused, match="all 1 of its runs"):
            await admitter.admit_due(schedule, now=NOON, manual=True)

        after = await schedules.get(schedule.schedule_id)
        assert after == before
        assert len(runs._runs) == 0  # type: ignore[attr-defined]

    async def test_a_retry_after_exhaustion_reconciles_to_the_winners_run(self, harness) -> None:
        """The same token on an exhausted schedule is a retry, not a new fire.

        The winner spent the last `max_runs` unit, so every refusal this
        admitter can raise — the snapshot check, `reserve_fire` — would tell a
        retried caller "could not be fired" about a fire whose Run
        demonstrably exists. The claim is asked before any of them (#1120):
        the loser is handed the winner's receipt, nothing is counted twice,
        and the disable the winner earned stands.
        """
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=1)

        first = await admitter.admit_due(schedule, now=NOON, manual=True, fire_id="retry-1")
        assert len(first.run_ids) == 1
        current = await schedules.get(schedule.schedule_id)
        assert current is not None
        assert current.enabled is False, "the winner's fire spent the bound"

        second = await admitter.admit_due(
            current, now=NOON + timedelta(minutes=1), manual=True, fire_id="retry-1"
        )

        assert second.run_ids == ()
        assert second.reconciled_run_id == first.run_ids[0]
        assert len(runs._runs) == 1  # type: ignore[attr-defined]
        recorded = await schedules.get(schedule.schedule_id)
        assert recorded is not None
        assert recorded.runs_so_far == 1
        assert recorded.enabled is False

    async def test_a_retry_after_the_template_disappeared_still_reconciles(self, harness) -> None:
        """The Run exists; there is nothing left to resolve for it.

        A retry whose target template has since been deleted reconciles to
        the winner rather than surfacing `GraphTemplateNotFound` — the fire
        happened, and the claim answers before the template is consulted
        (#1120).
        """
        admitter, runs, templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        first = await admitter.admit_due(schedule, now=NOON, manual=True, fire_id="retry-1")
        # The in-memory store has no delete; evict it the way the store does.
        templates._templates.pop((TEMPLATE_ID, 1))  # type: ignore[attr-defined]

        second = await admitter.admit_due(
            schedule, now=NOON + timedelta(minutes=1), manual=True, fire_id="retry-1"
        )

        assert second.reconciled_run_id == first.run_ids[0]
        assert len(runs._runs) == 1  # type: ignore[attr-defined]

    async def test_an_unresolvable_template_refuses_and_keeps_the_schedule_unchanged(
        self, harness
    ) -> None:
        """The durable template is the authority; refusing touches nothing."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, graph_template_id="nope")
        before = await schedules.get(schedule.schedule_id)

        with pytest.raises(GraphTemplateNotFound):
            await admitter.admit_due(schedule, now=NOON, manual=True)

        after = await schedules.get(schedule.schedule_id)
        assert after == before
        assert len(runs._runs) == 0  # type: ignore[attr-defined]

    async def test_a_failed_run_creation_keeps_the_schedule_unchanged(
        self, harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        before = await schedules.get(schedule.schedule_id)

        async def _fail(*args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic create failure")

        monkeypatch.setattr(runs, "create_run", _fail)
        with pytest.raises(RuntimeError):
            await admitter.admit_due(schedule, now=NOON, manual=True)

        after = await schedules.get(schedule.schedule_id)
        assert after == before

    async def test_a_claimed_occurrence_is_reported_not_recreated(self, harness) -> None:
        """Two fires racing on the same identity produce one Run (#220, #1120).

        The identity of a manual fire is its `fire_id` token — not the
        instant, which minted a fresh identity per call and turned every
        retry into a second Run. Two admissions carrying one token are one
        logical firing: the second reports `already_fired` and hands back the
        winner's Run.
        """
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)

        first = await admitter.admit_due(schedule, now=NOON, manual=True, fire_id="retry-1")
        second = await admitter.admit_due(schedule, now=NOON, manual=True, fire_id="retry-1")

        assert len(first.run_ids) == 1
        assert second.run_ids == ()
        assert second.already_fired == (NOON,)
        assert second.reconciled_run_id == first.run_ids[0]
        assert len(runs._runs) == 1  # type: ignore[attr-defined]
        recorded = await schedules.get(schedule.schedule_id)
        assert recorded is not None
        assert recorded.runs_so_far == 1, "a fire that already happened counts once"
