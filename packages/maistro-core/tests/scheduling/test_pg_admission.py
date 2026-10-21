"""Live PostgreSQL admission races for scheduled occurrences (#220)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from maistro.graph.definitions import GraphTemplate, Node
from maistro.graph.templates import InMemoryGraphTemplateStore
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.pg_store import PgRunStore
from maistro.runs.sources import canonical_occurrence_instant
from maistro.scheduling.admission import ScheduleRunAdmitter
from maistro.scheduling.model import OverlapPolicy, Schedule
from maistro.scheduling.pg_store import PgScheduleStore

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_two_admitters_concurrently_claim_each_due_occurrence_once(
    pg_pool: Any,
) -> None:
    """Two PostgreSQL-backed tickers share each nominal occurrence exactly once."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")

    workspace = f"issue-220-{uuid4().hex}"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name="Concurrent schedule",
    )

    templates = InMemoryGraphTemplateStore()
    await templates.put(
        GraphTemplate(
            template_id="issue-220-template",
            workspace_id=workspace,
            name="Concurrent schedule template",
            nodes=[Node(node_id="node-1", node_type="agent", name="agent")],
        )
    )
    schedule = Schedule(
        schedule_id=f"issue-220-schedule-{uuid4().hex}",
        workspace_id=workspace,
        project_id=project.project_id,
        cron="0 * * * *",
        graph_template_id="issue-220-template",
        overlap_policy=OverlapPolicy.ALLOW,
        catchup_window_seconds=6 * 3600,
        created_at=NOON - timedelta(days=1),
        last_fired_at=NOON - timedelta(hours=3),
        next_due_at=NOON - timedelta(minutes=1),
    )
    schedule_store_a = PgScheduleStore(pg_pool)
    schedule_store_b = PgScheduleStore(pg_pool)
    await schedule_store_a.put(schedule)

    # Separate store/admitter objects model two ticker replicas. Both receive
    # the same stale schedule snapshot before either starts admitting.
    snapshot_a = await schedule_store_a.get(schedule.schedule_id)
    snapshot_b = await schedule_store_b.get(schedule.schedule_id)
    assert snapshot_a is not None and snapshot_b is not None
    admitter_a = ScheduleRunAdmitter(
        PgRunStore(pg_pool, project_store=projects), templates, schedule_store_a
    )
    admitter_b = ScheduleRunAdmitter(
        PgRunStore(pg_pool, project_store=projects), templates, schedule_store_b
    )

    first, second = await asyncio.gather(
        admitter_a.admit_due(snapshot_a, now=NOON),
        admitter_b.admit_due(snapshot_b, now=NOON),
    )

    run_ids = first.run_ids + second.run_ids
    assert len(run_ids) == 3
    assert len(set(run_ids)) == 3
    assert len(first.already_fired + second.already_fired) == 3

    rows = await pg_pool.fetch(
        """SELECT payload->'provenance'->>'scheduled_for' AS scheduled_for,
                  count(*) AS count
           FROM canonical_runs
           WHERE payload->'provenance'->>'schedule_id' = $1
           GROUP BY payload->'provenance'->>'scheduled_for'
           ORDER BY scheduled_for""",
        schedule.schedule_id,
    )
    assert [(row["scheduled_for"], row["count"]) for row in rows] == [
        ((NOON - timedelta(hours=2)).isoformat(), 1),
        ((NOON - timedelta(hours=1)).isoformat(), 1),
        (NOON.isoformat(), 1),
    ]


@pytest.mark.asyncio
async def test_admitters_on_opposite_sides_of_a_timezone_edit_claim_each_instant_once(
    pg_pool: Any,
) -> None:
    """Two replicas ticking across a timezone edit still share each instant.

    The edit (#850) is exactly what used to break the race: replica A still
    holds the pre-edit UTC snapshot, replica B reads the post-edit row whose
    occurrences render `+02:00`. The same three instants enumerate on both
    sides under two different wall clocks, and before the claims were written
    as canonical instants each replica's inserts looked brand new to the other
    — six Runs for three firings. On real PostgreSQL, two pools' connections,
    simultaneously: the claim index, not the wall clock, decides.
    """
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")

    workspace = f"issue-850-{uuid4().hex}"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name="Timezone-edit race",
    )

    templates = InMemoryGraphTemplateStore()
    await templates.put(
        GraphTemplate(
            template_id="issue-850-template",
            workspace_id=workspace,
            name="Timezone-edit race template",
            nodes=[Node(node_id="node-1", node_type="agent", name="agent")],
        )
    )
    schedule = Schedule(
        schedule_id=f"issue-850-schedule-{uuid4().hex}",
        workspace_id=workspace,
        project_id=project.project_id,
        cron="0 * * * *",
        graph_template_id="issue-850-template",
        overlap_policy=OverlapPolicy.ALLOW,
        catchup_window_seconds=6 * 3600,
        created_at=NOON - timedelta(days=1),
        last_fired_at=NOON - timedelta(hours=3),
        next_due_at=NOON - timedelta(minutes=1),
    )
    store_a = PgScheduleStore(pg_pool)
    store_b = PgScheduleStore(pg_pool)
    await store_a.put(schedule)

    # The operator's edit lands before either replica ticks: replica B's row
    # has no due cursor (the recurrence changed) and renders in Berlin, while
    # replica A still holds the UTC snapshot it read before the edit.
    snapshot_a = await store_a.get(schedule.schedule_id)
    assert snapshot_a is not None
    await store_b.put(snapshot_a.model_copy(update={"timezone": "Europe/Berlin"}))
    snapshot_b = await store_b.get(schedule.schedule_id)
    assert snapshot_b is not None
    assert snapshot_b.next_due_at is None

    admitter_a = ScheduleRunAdmitter(
        PgRunStore(pg_pool, project_store=projects), templates, store_a
    )
    admitter_b = ScheduleRunAdmitter(
        PgRunStore(pg_pool, project_store=projects), templates, store_b
    )
    first, second = await asyncio.gather(
        admitter_a.admit_due(snapshot_a, now=NOON),
        admitter_b.admit_due(snapshot_b, now=NOON),
    )

    run_ids = first.run_ids + second.run_ids
    assert len(run_ids) == 3
    assert len(set(run_ids)) == 3
    assert len(first.already_fired + second.already_fired) == 3

    rows = await pg_pool.fetch(
        """SELECT payload->'provenance'->>'scheduled_for' AS scheduled_for,
                  count(*) AS count
           FROM canonical_runs
           WHERE payload->'provenance'->>'schedule_id' = $1
           GROUP BY payload->'provenance'->>'scheduled_for'
           ORDER BY scheduled_for""",
        schedule.schedule_id,
    )
    # Three firings, one Run each, and every claim written as the canonical
    # instant: no wall-clock rendering survived, so neither replica's text
    # could masquerade as a different occurrence.
    assert [(row["scheduled_for"], row["count"]) for row in rows] == [
        (canonical_occurrence_instant(NOON - timedelta(hours=2)), 1),
        (canonical_occurrence_instant(NOON - timedelta(hours=1)), 1),
        (canonical_occurrence_instant(NOON), 1),
    ]

    # The shared row converged under both writers: each occurrence counted
    # exactly once, by whichever replica won its claim.
    stored = await store_a.get(schedule.schedule_id)
    assert stored is not None
    assert stored.enabled is True
    assert stored.runs_so_far == 3
    assert stored.last_fired_at == NOON
