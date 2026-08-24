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
