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

from datetime import UTC, datetime, timedelta

import pytest

from maistro.graph.definitions import GraphTemplate, Node
from maistro.graph.templates import GraphTemplateNotFound, InMemoryGraphTemplateStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
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
        """`next_due_at` still moved and the caller wants it — but writing it
        through `record_fire` would stamp `last_fired_at` for a fire that did
        not happen."""
        admitter, _runs, _templates, schedules, project_id = harness
        schedule = await _schedule(schedules, project_id, last_fired_at=NOON)
        before = await schedules.get(schedule.schedule_id)

        result = await admitter.admit_due(schedule, now=NOON)

        after = await schedules.get(schedule.schedule_id)
        assert result.run_ids == ()
        assert result.next_due_at is not None
        assert after is not None and before is not None
        assert after.last_fired_at == before.last_fired_at


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
