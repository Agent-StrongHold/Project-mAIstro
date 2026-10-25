"""PostgreSQL persistence keeps a schedule's scope fields intact (#1201).

The canonical ScheduleStore migration (#1199) must preserve ``workspace_id``,
``project_id``, and ``actor_principal_id`` rather than projecting them away —
a durable row that forgets its scope would let a later tick fire with a
defaulted (unscoped or ownerless) identity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from maistro.scheduling.model import Schedule
from maistro.scheduling.pg_store import PgScheduleStore


@pytest.mark.asyncio
async def test_pg_schedule_round_trip_preserves_scope_fields(pg_pool: Any) -> None:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")

    store = PgScheduleStore(pg_pool)
    schedule_id = f"issue-1201-{uuid4().hex}"
    await store.put(
        Schedule(
            schedule_id=schedule_id,
            workspace_id="ws-1201",
            project_id="proj-1201",
            name="scoped",
            cron="0 9 * * *",
            timezone="UTC",
            graph_template_id="tpl-1201",
            actor_principal_id="principal-1201",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )

    stored = await store.get(schedule_id)
    assert stored is not None
    assert stored.workspace_id == "ws-1201"
    assert stored.project_id == "proj-1201"
    assert stored.actor_principal_id == "principal-1201"

    # The project-scoped listing is the seam scope-aware callers read.
    listed = await store.list_for_project(workspace_id="ws-1201", project_id="proj-1201")
    assert [s.schedule_id for s in listed] == [schedule_id]
    assert listed[0].actor_principal_id == "principal-1201"

    # A cursor advance rewrites the row; the scope fields must survive it.
    await store.record_fire(schedule_id, fired_at=None, run_id=None, next_due_at=None)
    advanced = await store.get(schedule_id)
    assert advanced is not None
    assert advanced.actor_principal_id == "principal-1201"
    assert advanced.workspace_id == "ws-1201"
    assert advanced.project_id == "proj-1201"
