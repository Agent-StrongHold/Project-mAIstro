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

import pytest

from maistro.graph.definitions import GraphTemplate, Node
from maistro.graph.templates import GraphTemplateNotFound, InMemoryGraphTemplateStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_INPUTS_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
)
from maistro.runs.store import InMemoryRunStore
from maistro.scheduling.admission import ScheduleRunAdmitter
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


async def _crashed_before_record_fire(harness, schedule: Schedule, when: datetime) -> str:
    """Ticker A's half of the #1059 sequence: the Run for `when` exists and
    the cursor was never stamped, which is exactly what dying between
    `create_run` and `record_fire` leaves behind."""
    admitter, _runs, templates, _schedules, _project_id = harness
    template = await templates.get(TEMPLATE_ID)
    assert template is not None
    return await admitter._admit_one(schedule, template, FireDecision(scheduled_for=when))


class TestADuplicateClaimLinksTheWinningRun:
    """Recovering the Run that won an occurrence claim (#1059).

    Occurrence uniqueness (#220) stops a second Run for `(schedule_id,
    scheduled_for)`; it did not say which Run won. A ticker refused with
    `DuplicateOccurrence` advanced the cursor with `run_id=None`, so
    `Schedule.last_run_id` stayed stale while the winner was live, the caller
    answered `active_run` from the wrong Run, and a SKIP schedule admitted a
    later occurrence on top of the one still running.
    """

    async def test_a_crash_before_record_fire_links_the_winner_on_the_next_tick(
        self, harness
    ) -> None:
        """The issue's sequence: ticker A creates the Run for T and dies before
        `record_fire`; ticker B re-enumerates T, is refused, and must leave
        `last_run_id` naming A's Run rather than nothing."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id)
        winner = await _crashed_before_record_fire(harness, schedule, NOON)
        before = await schedules.get(schedule.schedule_id)
        assert before is not None and before.last_run_id is None

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert result.run_ids == ()
        assert result.already_fired == (NOON,)
        assert stored is not None
        assert stored.last_run_id == winner
        assert stored.last_fired_at == NOON

    async def test_skip_is_judged_against_the_winning_run_once_it_is_linked(self, harness) -> None:
        """The property the link buys. `evaluate()`'s contract is that the
        caller answers `active_run` from Run state via `last_run_id`, so a
        stale pointer was a SKIP schedule that could not see its own in-flight
        Run and ran the next occurrence beside it."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.SKIP)
        await _crashed_before_record_fire(harness, schedule, NOON)
        await admitter.admit_due(schedule, now=NOON)
        linked = await schedules.get(schedule.schedule_id)
        assert linked is not None and linked.last_run_id is not None
        winner = await runs.get_run(linked.last_run_id)
        assert winner is not None
        active = winner.status not in TERMINAL_RUN_STATUSES
        assert active is True

        later = await admitter.admit_due(linked, now=NOON + timedelta(hours=1), active_run=active)

        assert later.run_ids == ()
        assert [skip.reason for skip in later.skipped] == [SkipReason.OVERLAP]

    async def test_a_finished_winner_is_linked_but_does_not_block_the_next_occurrence(
        self, harness
    ) -> None:
        """Linked truthfully -- it is the latest occurrence's Run -- while a
        terminal Run is not an active one, so the next occurrence fires."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, overlap_policy=OverlapPolicy.SKIP)
        winner = await _crashed_before_record_fire(harness, schedule, NOON)
        await runs.transition_run(winner, RunStatus.CANCELLED, error="operator")
        await admitter.admit_due(schedule, now=NOON)
        linked = await schedules.get(schedule.schedule_id)
        assert linked is not None and linked.last_run_id == winner
        run = await runs.get_run(winner)
        assert run is not None
        active = run.status not in TERMINAL_RUN_STATUSES
        assert active is False

        later = await admitter.admit_due(linked, now=NOON + timedelta(hours=1), active_run=active)

        assert len(later.run_ids) == 1
        after = await schedules.get(schedule.schedule_id)
        assert after is not None and after.last_run_id == later.run_ids[0]

    async def test_two_tickers_racing_one_occurrence_converge_on_one_run_and_cursor(
        self, harness
    ) -> None:
        """Whichever ticker loses the claim links the other's Run, so both end
        with the same `last_run_id`, one fire counted, and the cursor on T."""
        admitter, runs, templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=4)
        rival = ScheduleRunAdmitter(runs, templates, schedules)

        first, second = await asyncio.gather(
            admitter.admit_due(schedule, now=NOON), rival.admit_due(schedule, now=NOON)
        )

        created = first.run_ids + second.run_ids
        assert len(created) == 1
        assert sorted((first.already_fired, second.already_fired)) == [(), (NOON,)]
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == created[0]
        assert stored.runs_so_far == 1
        assert stored.last_fired_at == NOON

    async def test_the_pointer_follows_the_newest_occurrence_whoever_admitted_it(
        self, harness
    ) -> None:
        """Under ALLOW a batch mixes this ticker's Runs with a rival's. The
        pointer is the Run behind the newest *consumed* occurrence, not the
        newest Run of ours -- an older Run of ours would be less true."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            last_fired_at=NOON - timedelta(hours=3),
            catchup_window_seconds=6 * 3600.0,
            overlap_policy=OverlapPolicy.ALLOW,
        )
        # A rival took the *newest* of the three due occurrences.
        rival = await _crashed_before_record_fire(harness, schedule, NOON)

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert len(result.run_ids) == 2
        assert result.already_fired == (NOON,)
        assert stored is not None
        assert stored.last_run_id == rival
        assert stored.last_run_id not in result.run_ids

    async def test_an_unresolvable_winner_leaves_the_pointer_where_it_was(self, harness) -> None:
        """The stores only evict or purge a *terminal* Run, so a claim whose
        Run cannot be found is one that finished. Nothing live is owed a link,
        and both clearing the pointer and refusing the batch would be wrong."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, last_run_id="an-earlier-run")
        await _crashed_before_record_fire(harness, schedule, NOON)

        async def _gone(schedule_id: str, scheduled_for: str) -> None:
            return None

        runs.get_run_for_occurrence = _gone  # type: ignore[method-assign]

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert result.already_fired == (NOON,)
        assert stored is not None
        assert stored.last_run_id == "an-earlier-run"
        assert stored.last_fired_at == NOON


class TestRecoverySeesTheRunStoreBeforeThePolicy:
    """The #1059 review's findings on the linkage change.

    A crashed winner is a Run with no pointer to it. The overlap policy used
    to be applied from the caller's stale `active_run`, so under CANCEL_OTHER
    the crashed occurrence fell into `skipped` — never reaching the duplicate
    handler — while the newer occurrence was admitted beside its live Run with
    no cancellation asked for, and the crashed firing was never counted.
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
        assert later.skipped == ()
        assert later.cancel_active_run is True, "the live crashed winner is the in-flight Run"
        assert later.active_run_id == winner
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == later.run_ids[0], "the pointer follows the newest occurrence"
        assert stored.last_fired_at == NOON + timedelta(hours=1)
        assert stored.runs_so_far == 2, "the crashed winner and the new fire both count"
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
        assert [skip.reason for skip in later.skipped] == [SkipReason.OVERLAP]
        assert later.active_run_id == winner
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None
        assert stored.last_run_id == winner
        assert stored.last_fired_at == NOON + timedelta(hours=1), "the overlap skip is consumed"
        assert stored.runs_so_far == 1

    async def test_a_crash_recovered_winner_is_counted_and_can_exhaust_the_schedule(
        self, harness
    ) -> None:
        """`max_runs=1`: the winner's ticker died before counting its fire.
        Recovery must count it — once — or the schedule fires a second time."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, max_runs=1)
        await _crashed_before_record_fire(harness, schedule, NOON)

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert result.already_fired == (NOON,)
        assert result.disabled is True
        assert stored is not None
        assert stored.runs_so_far == 1
        assert stored.enabled is False
        again = await admitter.admit_due(stored, now=NOON + timedelta(hours=1))
        assert again.run_ids == ()

    async def test_two_tickers_consuming_one_occurrence_count_it_once(self, harness) -> None:
        """The counting is idempotent at the cursor, so the refused ticker and
        the winning ticker both pass the occurrence to the store and it is
        counted by whichever writes first."""
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

    async def test_an_unresolvable_newest_winner_yields_the_pointer_to_our_newest_run(
        self, harness
    ) -> None:
        """Under ALLOW, ours for T-2h and T-1h; a rival's for T whose Run is
        gone (only ever a finished one). The pointer is the next newest known
        Run — ours for T-1h, which may still be live — not the one from before
        the batch, and not nothing."""
        admitter, runs, _templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            last_fired_at=NOON - timedelta(hours=3),
            catchup_window_seconds=6 * 3600.0,
            overlap_policy=OverlapPolicy.ALLOW,
            last_run_id="an-earlier-run",
        )
        rival = await _crashed_before_record_fire(harness, schedule, NOON)
        await runs.transition_run(rival, RunStatus.CANCELLED, error="operator")
        real_lookup = runs.get_run_for_occurrence

        async def _gone_for_noon(schedule_id: str, scheduled_for: str):
            if scheduled_for == NOON.isoformat():
                return None
            return await real_lookup(schedule_id, scheduled_for)

        runs.get_run_for_occurrence = _gone_for_noon  # type: ignore[method-assign]

        result = await admitter.admit_due(schedule, now=NOON)

        stored = await schedules.get(schedule.schedule_id)
        assert len(result.run_ids) == 2
        assert result.already_fired == (NOON,)
        assert stored is not None
        assert stored.last_run_id == result.run_ids[-1]
        assert stored.last_fired_at == NOON
        assert stored.runs_so_far == 3, "the rival's firing still counts"

    async def test_a_delayed_ticker_cannot_move_the_cursor_backward(self, harness) -> None:
        """Two ALLOW tickers with different horizons: the one that evaluated
        only T-1h stalls after creating its Run; another records through T;
        the stalled one then records T-1h. The cursor and pointer stay on T."""
        admitter, runs, templates, schedules, project_id = harness
        schedule = await _schedule(
            schedules,
            project_id,
            last_fired_at=NOON - timedelta(hours=2),
            overlap_policy=OverlapPolicy.ALLOW,
        )
        rival = ScheduleRunAdmitter(runs, templates, schedules)
        stalled = await rival.admit_due(schedule, now=NOON - timedelta(hours=1))
        assert stalled.run_ids and (await schedules.get(schedule.schedule_id)).last_fired_at == (
            NOON - timedelta(hours=1)
        )
        # The other ticker evaluated the same snapshot but a later horizon.
        ahead = await admitter.admit_due(schedule, now=NOON)
        stored = await schedules.get(schedule.schedule_id)
        assert stored is not None and stored.last_fired_at == NOON
        assert stored.last_run_id == ahead.run_ids[-1]

        # The stalled ticker's write arrives last, carrying its older cursor.
        await schedules.record_fire(
            schedule.schedule_id,
            fired_at=NOON - timedelta(hours=1),
            run_id=stalled.run_ids[0],
            next_due_at=NOON,
            fires=0,
            fired=[NOON - timedelta(hours=1)],
        )

        final = await schedules.get(schedule.schedule_id)
        assert final is not None
        assert final.last_fired_at == NOON
        assert final.last_run_id == ahead.run_ids[-1]
        assert final.next_due_at == stored.next_due_at
        assert final.runs_so_far == 2
