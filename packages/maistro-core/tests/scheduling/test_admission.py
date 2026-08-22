"""A schedule firing produces a canonical Run (#145).

`maistro.scheduling` was a complete decision engine that nothing called, and
`hive-conductor`'s schedule API stamped a timestamp and executed nothing. Those
two halves had never been connected. This is the connection, and what it has to
get right is mostly about *which* occurrence a Run belongs to — the nominal fire
time, not the moment a tick noticed it — and about not advancing the schedule's
cursor past work that never ran.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.graph.definitions import Edge, GraphTemplate, Node
from maistro.graph.templates import GraphTemplateNotFound, InMemoryGraphTemplateStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import ADMISSION_SOURCE
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.scheduling.admission import (
    CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
    ScheduleRunAdmitter,
)
from maistro.scheduling.engine import FireDecision, SkipReason
from maistro.scheduling.model import OverlapPolicy, Schedule
from maistro.scheduling.store import InMemoryScheduleStore

WORKSPACE = "schedule-workspace"
TEMPLATE_ID = "daily-status"
# 09:00 on the hour, so "one hour later" is exactly one occurrence.
NOON = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
async def seam():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    runs = InMemoryRunStore(project_store=projects)
    schedules = InMemoryScheduleStore()
    templates = InMemoryGraphTemplateStore()
    await templates.put(
        GraphTemplate(
            template_id=TEMPLATE_ID,
            workspace_id=WORKSPACE,
            name="daily status",
            nodes=[
                Node(node_id="n1", node_type="agent", name="gather"),
                Node(node_id="n2", node_type="agent", name="report"),
            ],
            edges=[Edge(edge_id="e1", from_node="n1", to_node="n2")],
        )
    )
    admitter = ScheduleRunAdmitter(runs, schedules, templates)
    return admitter, runs, schedules, templates, root.project_id


async def _schedule(seam, **overrides) -> Schedule:
    _admitter, _runs, schedules, _templates, project_id = seam
    fields = {
        "workspace_id": WORKSPACE,
        "project_id": project_id,
        "name": "daily status",
        "cron": "0 * * * *",
        "graph_template_id": TEMPLATE_ID,
        "created_at": NOON - timedelta(days=1),
        **overrides,
    }
    return await schedules.put(Schedule(**fields))


# ── the Run a fire produces ───────────────────────────────────────


async def test_a_fire_produces_a_resolvable_run(seam) -> None:
    admitter, runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam)

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    assert await runs.get_run(run.run_id) is not None
    assert run.status is RunStatus.CREATED


async def test_the_run_is_the_instantiated_template(seam) -> None:
    """Not a one-node stand-in like a task or a chat turn: a schedule names a
    Graph somebody drew, and firing instantiates it."""
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam)

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    graph = run.graph.materialize()
    assert [node.name for node in graph.nodes] == ["gather", "report"]
    assert len(graph.edges) == 1


async def test_the_run_cites_the_template_version_it_ran(seam) -> None:
    admitter, _runs, _schedules, templates, _project = seam
    schedule = await _schedule(seam)
    registered = await templates.get(TEMPLATE_ID)
    assert registered is not None

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    provenance = run.graph.materialize().source_template
    assert provenance is not None
    assert provenance.template_id == TEMPLATE_ID
    assert provenance.template_hash == registered.content_hash


async def test_a_pinned_version_is_the_one_that_runs(seam) -> None:
    admitter, _runs, _schedules, templates, _project = seam
    await templates.put(
        GraphTemplate(
            template_id=TEMPLATE_ID,
            workspace_id=WORKSPACE,
            version=2,
            name="daily status",
            nodes=[Node(node_id="n1", node_type="agent", name="rewritten")],
        )
    )
    schedule = await _schedule(seam, template_version=1)

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    assert [node.name for node in run.graph.materialize().nodes] == ["gather", "report"]


async def test_an_unregistered_template_refuses_the_fire(seam) -> None:
    """A Run over an empty Graph would be a canonical-looking record of work
    that can never run — the same refusal `runs.admission` makes for an
    unregistered node kind."""
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam, graph_template_id="nobody-registered-this")

    with pytest.raises(GraphTemplateNotFound):
        await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))


# ── provenance: which occurrence this Run belongs to ──────────────


async def test_provenance_names_the_schedule_and_the_source(seam) -> None:
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam)

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    assert run.provenance[ADMISSION_SOURCE] == SCHEDULE_SOURCE
    assert run.provenance[SCHEDULE_ID_KEY] == schedule.schedule_id


async def test_provenance_records_the_nominal_fire_time(seam) -> None:
    """A Run that started twenty minutes late still belongs to the 12:00
    occurrence, and only this field says so."""
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam)

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    assert run.provenance[SCHEDULED_FOR_KEY] == NOON.isoformat()


async def test_a_catchup_fire_says_so(seam) -> None:
    """A backfill after downtime and an on-time fire are indistinguishable
    afterwards, and they mean different things to whoever reads the Run."""
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam)

    on_time = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))
    backfill = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON, catchup=True))

    assert on_time.provenance[CATCHUP_KEY] is False
    assert backfill.provenance[CATCHUP_KEY] is True


async def test_the_schedules_inputs_travel_with_the_run(seam) -> None:
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam, inputs={"region": "eu"})

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    assert run.provenance["inputs"] == {"region": "eu"}


async def test_the_principal_and_persona_carry_over(seam) -> None:
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam, actor_principal_id="alice", persona_id="scribe")

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    assert run.actor_principal_id == "alice"
    assert run.persona_id == "scribe"


async def test_a_scheduled_run_is_retained_indefinitely_by_default(seam) -> None:
    """Whether recurring work gets a retention deadline is a policy decision
    nobody has made (#145). The default must be today's behavior, not a bound
    inherited by accident."""
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam)

    run = await admitter.admit_fire(schedule, FireDecision(scheduled_for=NOON))

    assert run.retention_expires_at is None


# ── fire_due: evaluation, admission and cursor advance together ───


async def test_a_due_schedule_fires_and_records_its_run(seam) -> None:
    admitter, runs, schedules, _templates, _project = seam
    schedule = await _schedule(seam, last_fired_at=NOON, next_due_at=NOON + timedelta(hours=1))

    decision, fired = await admitter.fire_due(schedule, now=NOON + timedelta(hours=1))

    assert len(decision.fires) == 1
    assert len(fired) == 1
    advanced = await schedules.get(schedule.schedule_id)
    assert advanced is not None
    assert advanced.last_run_id == fired[0].run_id
    assert await runs.get_run(advanced.last_run_id) is not None


async def test_the_cursor_advances_to_the_nominal_time(seam) -> None:
    """Not to `now`. Advancing to the wall clock would silently swallow every
    occurrence between the fire and the moment the tick ran."""
    admitter, _runs, schedules, _templates, _project = seam
    schedule = await _schedule(seam, last_fired_at=NOON, next_due_at=NOON + timedelta(hours=1))

    decision, _fired = await admitter.fire_due(schedule, now=NOON + timedelta(hours=1, minutes=30))

    advanced = await schedules.get(schedule.schedule_id)
    assert advanced is not None
    assert advanced.last_fired_at == decision.fires[-1].scheduled_for


async def test_a_schedule_that_is_not_due_fires_nothing(seam) -> None:
    admitter, _runs, schedules, _templates, _project = seam
    schedule = await _schedule(seam, last_fired_at=NOON, next_due_at=NOON + timedelta(hours=1))

    _decision, fired = await admitter.fire_due(schedule, now=NOON + timedelta(minutes=10))

    assert fired == []
    unchanged = await schedules.get(schedule.schedule_id)
    assert unchanged is not None
    assert unchanged.runs_so_far == 0


async def test_a_disabled_schedule_fires_nothing(seam) -> None:
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam, enabled=False, last_fired_at=NOON)

    _decision, fired = await admitter.fire_due(schedule, now=NOON + timedelta(hours=2))

    assert fired == []


async def test_an_overlapping_fire_is_skipped_and_reported(seam) -> None:
    """The engine reports refusals rather than dropping them; the admitter has
    to hand that back or the distinction is lost at the seam."""
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(
        seam,
        overlap_policy=OverlapPolicy.SKIP,
        last_fired_at=NOON,
        next_due_at=NOON + timedelta(hours=1),
    )

    decision, fired = await admitter.fire_due(
        schedule, now=NOON + timedelta(hours=1), active_run=True
    )

    assert fired == []
    assert [skip.reason for skip in decision.skipped] == [SkipReason.OVERLAP]


async def test_the_default_policy_fires_one_occurrence_per_evaluation(seam) -> None:
    """Under SKIP — the default — the first occurrence of a backlog fires and
    becomes the in-flight Run, so the rest of the batch overlaps it. Worth
    pinning: it is why a missed night does not produce a thundering herd."""
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(
        seam,
        last_fired_at=NOON,
        next_due_at=NOON + timedelta(hours=1),
        catchup_window_seconds=86400,
    )

    decision, fired = await admitter.fire_due(schedule, now=NOON + timedelta(hours=3))

    assert len(fired) == 1
    assert [skip.reason for skip in decision.skipped] == [
        SkipReason.OVERLAP,
        SkipReason.OVERLAP,
    ]


async def test_a_catchup_backlog_produces_one_run_per_occurrence(seam) -> None:
    """Each occurrence is its own Run — collapsing three missed hours into one
    would lose which occurrences ran. ALLOW is the policy that says a backlog
    should actually be worked through."""
    admitter, _runs, schedules, _templates, _project = seam
    schedule = await _schedule(
        seam,
        overlap_policy=OverlapPolicy.ALLOW,
        last_fired_at=NOON,
        next_due_at=NOON + timedelta(hours=1),
        catchup_window_seconds=86400,
    )

    _decision, fired = await admitter.fire_due(schedule, now=NOON + timedelta(hours=3))

    assert len(fired) == 3
    scheduled_for = [run.provenance[SCHEDULED_FOR_KEY] for run in fired]
    assert scheduled_for == sorted(scheduled_for)
    advanced = await schedules.get(schedule.schedule_id)
    assert advanced is not None
    assert advanced.runs_so_far == 3


# ── max_runs ──────────────────────────────────────────────────────


async def test_reaching_max_runs_disables_the_schedule(seam) -> None:
    """`ScheduleEvaluation.exhausted` has always reported this and nothing
    consumed it, so a bounded schedule ran forever."""
    admitter, _runs, schedules, _templates, _project = seam
    schedule = await _schedule(
        seam, max_runs=1, last_fired_at=NOON, next_due_at=NOON + timedelta(hours=1)
    )

    _decision, fired = await admitter.fire_due(schedule, now=NOON + timedelta(hours=1))

    assert len(fired) == 1
    spent = await schedules.get(schedule.schedule_id)
    assert spent is not None
    assert spent.enabled is False
    assert spent.next_due_at is None


async def test_max_runs_bounds_a_catchup_backlog(seam) -> None:
    """Two occurrences due and one run remaining: one Run, not two."""
    admitter, _runs, schedules, _templates, _project = seam
    schedule = await _schedule(
        seam,
        max_runs=1,
        overlap_policy=OverlapPolicy.ALLOW,
        last_fired_at=NOON,
        next_due_at=NOON + timedelta(hours=1),
        catchup_window_seconds=86400,
    )

    decision, fired = await admitter.fire_due(schedule, now=NOON + timedelta(hours=2))

    assert len(fired) == 1
    assert SkipReason.EXHAUSTED in [skip.reason for skip in decision.skipped]
    spent = await schedules.get(schedule.schedule_id)
    assert spent is not None
    assert spent.enabled is False


async def test_an_exhausted_schedule_fires_nothing_further(seam) -> None:
    admitter, _runs, _schedules, _templates, _project = seam
    schedule = await _schedule(seam, max_runs=1, runs_so_far=1, last_fired_at=NOON)

    _decision, fired = await admitter.fire_due(schedule, now=NOON + timedelta(hours=5))

    assert fired == []


# ── the cursor never runs ahead of the Runs ───────────────────────


async def test_a_failed_admission_leaves_the_cursor_where_it_was(seam) -> None:
    """The cursor is advanced after the Runs exist, not before. Advancing first
    would skip an occurrence that never ran, permanently and silently."""
    admitter, _runs, schedules, _templates, _project = seam
    schedule = await _schedule(
        seam,
        graph_template_id="nobody-registered-this",
        last_fired_at=NOON,
        next_due_at=NOON + timedelta(hours=1),
    )

    with pytest.raises(GraphTemplateNotFound):
        await admitter.fire_due(schedule, now=NOON + timedelta(hours=1))

    unchanged = await schedules.get(schedule.schedule_id)
    assert unchanged is not None
    assert unchanged.last_fired_at == NOON
    assert unchanged.runs_so_far == 0


# ── the durable graph launch carries provenance too (#145) ────────


async def test_a_durable_graph_launch_records_its_provenance() -> None:
    """`run_durable_graph` stamped only `executor=durable_graph`, so a Run
    started by a schedule was indistinguishable from one started by hand and
    the linkage lived in an audit line beside the Run. The exported entry point
    is `attempt_executor`'s, not `traversal`'s — a parameter added only to the
    other is one no caller can reach."""
    from maistro.graph.definitions import Graph
    from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph

    graph = Graph(
        workspace_id="w",
        project_id="p",
        name="one node",
        nodes=[Node(node_id="n1", node_type="transform.format_markdown", name="only")],
    )

    record = await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda _node: None,
        provenance={ADMISSION_SOURCE: SCHEDULE_SOURCE, SCHEDULE_ID_KEY: "sched-1"},
    )

    assert record.run.provenance[ADMISSION_SOURCE] == SCHEDULE_SOURCE
    assert record.run.provenance[SCHEDULE_ID_KEY] == "sched-1"
    # The executor key stays authoritative — a caller cannot claim the Run ran
    # through something it did not.
    assert record.run.provenance["executor"] == "durable_graph"


async def test_a_caller_cannot_overwrite_the_executor_key() -> None:
    from maistro.graph.definitions import Graph
    from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph

    graph = Graph(
        workspace_id="w",
        project_id="p",
        name="one node",
        nodes=[Node(node_id="n1", node_type="transform.format_markdown", name="only")],
    )

    record = await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda _node: None,
        provenance={"executor": "something-else"},
    )

    assert record.run.provenance["executor"] == "durable_graph"
