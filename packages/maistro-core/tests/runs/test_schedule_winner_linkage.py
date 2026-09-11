"""A restarted ticker links the Run a dead ticker created (#1059).

`tests/scheduling/test_admission.py` holds the admitter's semantics on the
in-memory store. This is the crash the issue describes, on every backend the
occurrence claim is enforced on: ticker A creates the Run for occurrence T and
the process dies before `record_fire`; a *restarted* ticker B -- a fresh store
object over the same durable rows -- re-enumerates T, is refused by the claim,
and must come out with `last_run_id` naming A's Run, so the overlap policy it
evaluates next is judged against the Run that is actually in flight.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph.definitions import GraphTemplate, Node
from maistro.graph.templates import InMemoryGraphTemplateStore
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.scheduling.admission import ScheduleRunAdmitter
from maistro.scheduling.engine import FireDecision, SkipReason
from maistro.scheduling.model import OverlapPolicy, Schedule
from maistro.scheduling.store import InMemoryScheduleStore

pytestmark = [pytest.mark.contract("behavioral")]

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
TEMPLATE_ID = "hourly-report"


async def _dead_ticker_left_a_run(
    store: Any, workspace: str, project_id: str
) -> tuple[str, InMemoryGraphTemplateStore, InMemoryScheduleStore, Schedule]:
    """Ticker A's half: the Run for NOON exists, the cursor was never stamped."""
    templates = InMemoryGraphTemplateStore()
    template = await templates.put(
        GraphTemplate(
            template_id=TEMPLATE_ID,
            workspace_id=workspace,
            version=1,
            name="hourly report",
            nodes=[Node(node_id="n1", node_type="agent", name="a")],
        )
    )
    schedules = InMemoryScheduleStore()
    schedule = await schedules.put(
        Schedule(
            workspace_id=workspace,
            project_id=project_id,
            name="hourly",
            cron="0 * * * *",
            graph_template_id=TEMPLATE_ID,
            overlap_policy=OverlapPolicy.SKIP,
            created_at=NOON - timedelta(days=30),
            last_fired_at=NOON - timedelta(hours=1),
        )
    )
    ticker_a = ScheduleRunAdmitter(store, templates, schedules)
    winner = await ticker_a._admit_one(schedule, template, FireDecision(scheduled_for=NOON))
    return winner, templates, schedules, schedule


async def test_a_restarted_ticker_links_the_run_a_dead_ticker_created(schedule_spine: Any) -> None:
    store, workspace, project_id, reopen = schedule_spine
    winner, templates, schedules, schedule = await _dead_ticker_left_a_run(
        store, workspace, project_id
    )

    restarted = await reopen()
    ticker_b = ScheduleRunAdmitter(restarted, templates, schedules)
    result = await ticker_b.admit_due(schedule, now=NOON)

    stored = await schedules.get(schedule.schedule_id)
    assert result.run_ids == ()
    assert result.already_fired == (NOON,)
    assert stored is not None
    assert stored.last_run_id == winner
    linked = await restarted.get_run(winner)
    assert linked is not None
    assert linked.status is RunStatus.QUEUED


async def test_the_next_occurrence_is_judged_against_the_winning_run(schedule_spine: Any) -> None:
    """No overlap-policy weakening after the crash: the linked Run is live, so
    a SKIP schedule drops the next occurrence instead of running two at once."""
    store, workspace, project_id, reopen = schedule_spine
    _winner, templates, schedules, schedule = await _dead_ticker_left_a_run(
        store, workspace, project_id
    )
    restarted = await reopen()
    ticker_b = ScheduleRunAdmitter(restarted, templates, schedules)
    await ticker_b.admit_due(schedule, now=NOON)
    linked = await schedules.get(schedule.schedule_id)
    assert linked is not None and linked.last_run_id is not None
    in_flight = await restarted.get_run(linked.last_run_id)
    assert in_flight is not None
    active = in_flight.status not in TERMINAL_RUN_STATUSES

    later = await ticker_b.admit_due(linked, now=NOON + timedelta(hours=1), active_run=active)

    assert later.run_ids == ()
    assert [skip.reason for skip in later.skipped] == [SkipReason.OVERLAP]
    queued = await restarted.list_by_status(RunStatus.QUEUED, project_id=project_id)
    assert [run.run_id for run in queued] == [linked.last_run_id]
