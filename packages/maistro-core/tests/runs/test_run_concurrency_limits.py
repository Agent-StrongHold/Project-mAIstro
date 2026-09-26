"""Governed active root-Run ceilings, enforced by every RunStore (#1182).

Real stores on all three backends, the production claiming variants the spine
wiring ships. The PostgreSQL leg skips without `MAISTRO_TEST_PG_DSN`; CI runs it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.concurrency import (
    ACTIVE_ROOT_STATUSES,
    RunConcurrencyExceeded,
    RunConcurrencyLimits,
)
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import RunStatus
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_ID_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
)
from maistro.runs.store import DuplicateOccurrence, RunStore


@dataclass
class _Spine:
    store: RunStore
    projects: dict[str, str]

    def graph(self, workspace: str) -> Graph:
        return Graph(
            workspace_id=workspace,
            project_id=self.projects[workspace],
            name="bounded",
            nodes=[Node(node_id="node-1", node_type="agent")],
        )

    async def root(self, workspace: str, principal: str | None) -> Any:
        return await self.store.create_run(
            self.graph(workspace), actor_principal_id=principal, initial_status=RunStatus.QUEUED
        )

    async def move(self, run_id: str, target: RunStatus) -> None:
        run = await self.store.get_run(run_id)
        assert run is not None
        for step in transition_path(run.status, target):
            await self.store.transition_run(run_id, step)


async def _projects(scope_store: Any, workspaces: tuple[str, ...]) -> dict[str, str]:
    projects: dict[str, str] = {}
    for workspace in workspaces:
        root = await scope_store.create_root(workspace)
        project = await scope_store.create(
            workspace_id=workspace, parent_project_id=root.project_id, name="Bounded"
        )
        projects[workspace] = project.project_id
    return projects


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def spine(request: pytest.FixtureRequest, pg_pool: Any) -> AsyncIterator[_Spine]:
    from maistro.runs.consumer_claim import (
        ClaimingInMemoryRunStore,
        ClaimingPgRunStore,
        ClaimingSqliteRunStore,
    )

    suffix = uuid4().hex[:8]
    workspaces = (f"w1-{suffix}", f"w2-{suffix}")
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.projects.pg_scope_store import PgProjectScopeStore

        pg_projects = PgProjectScopeStore(pg_pool)
        yield _Spine(
            ClaimingPgRunStore(pg_pool, project_store=pg_projects),
            await _projects(pg_projects, workspaces),
        )
        return

    scope_store = InMemoryProjectScopeStore()
    projects = await _projects(scope_store, workspaces)
    if request.param == "memory":
        yield _Spine(ClaimingInMemoryRunStore(project_store=scope_store), projects)
        return

    conn = await aiosqlite.connect(":memory:")
    store = ClaimingSqliteRunStore(conn, project_store=scope_store)
    await store.ensure_schema()
    try:
        yield _Spine(store, projects)
    finally:
        await conn.close()


def _workspaces(spine: _Spine) -> tuple[str, str]:
    first, second = spine.projects
    return first, second


def test_owner_decided_ceilings_and_active_statuses() -> None:
    limits = RunConcurrencyLimits()
    assert (limits.per_principal, limits.per_workspace) == (8, 32)
    assert {RunStatus.CREATED, RunStatus.QUEUED, RunStatus.RUNNING} == ACTIVE_ROOT_STATUSES


async def test_ninth_active_root_run_for_one_principal_is_refused(spine: _Spine) -> None:
    w1, _ = _workspaces(spine)
    for _ in range(8):
        await spine.root(w1, "alice")

    with pytest.raises(RunConcurrencyExceeded) as refused:
        await spine.root(w1, "alice")

    assert (refused.value.scope, refused.value.limit, refused.value.active) == ("principal", 8, 8)


async def test_the_principal_ceiling_spans_workspaces(spine: _Spine) -> None:
    w1, w2 = _workspaces(spine)
    for _ in range(4):
        await spine.root(w1, "alice")
        await spine.root(w2, "alice")

    with pytest.raises(RunConcurrencyExceeded, match="principal"):
        await spine.root(w2, "alice")


async def test_thirty_third_active_root_run_in_one_workspace_is_refused(spine: _Spine) -> None:
    w1, _ = _workspaces(spine)
    for index in range(32):
        await spine.root(w1, f"user-{index % 8}" if index % 2 else None)

    with pytest.raises(RunConcurrencyExceeded) as refused:
        await spine.root(w1, "fresh-user")

    assert (refused.value.scope, refused.value.limit, refused.value.active) == ("workspace", 32, 32)


async def test_child_runs_hold_no_slot(spine: _Spine) -> None:
    w1, _ = _workspaces(spine)
    parent = await spine.root(w1, "alice")
    for _ in range(12):
        await spine.store.create_run(
            spine.graph(w1), parent_run_id=parent.run_id, actor_principal_id="alice"
        )

    for _ in range(7):
        await spine.root(w1, "alice")
    with pytest.raises(RunConcurrencyExceeded):
        await spine.root(w1, "alice")


@pytest.mark.parametrize(
    "target",
    [
        RunStatus.WAITING,
        RunStatus.PAUSED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
        RunStatus.FAILED,
    ],
)
async def test_parking_or_terminalizing_a_run_frees_its_slot(
    spine: _Spine, target: RunStatus
) -> None:
    w1, _ = _workspaces(spine)
    admitted = [await spine.root(w1, "alice") for _ in range(8)]
    with pytest.raises(RunConcurrencyExceeded):
        await spine.root(w1, "alice")

    await spine.move(admitted[0].run_id, target)

    await spine.root(w1, "alice")
    with pytest.raises(RunConcurrencyExceeded):
        await spine.root(w1, "alice")


async def test_a_parked_run_resuming_at_the_ceiling_is_not_a_new_admission(
    spine: _Spine,
) -> None:
    """Owner decision 2026-09-25: resume may exceed the ceiling."""
    w1, _ = _workspaces(spine)
    parked = await spine.root(w1, "alice")
    await spine.move(parked.run_id, RunStatus.PAUSED)
    for _ in range(8):
        await spine.root(w1, "alice")

    await spine.move(parked.run_id, RunStatus.QUEUED)

    resumed = await spine.store.get_run(parked.run_id)
    assert resumed is not None and resumed.status is RunStatus.QUEUED
    with pytest.raises(RunConcurrencyExceeded):
        await spine.root(w1, "alice")


async def test_a_saturated_principal_does_not_starve_another_principal_or_workspace(
    spine: _Spine,
) -> None:
    w1, w2 = _workspaces(spine)
    for _ in range(8):
        await spine.root(w1, "alice")
    with pytest.raises(RunConcurrencyExceeded):
        await spine.root(w1, "alice")

    await spine.root(w1, "bob")
    await spine.root(w2, "carol")
    await spine.root(w2, None)


async def test_a_saturated_workspace_does_not_starve_another_workspace(spine: _Spine) -> None:
    w1, w2 = _workspaces(spine)
    for index in range(32):
        await spine.root(w1, f"user-{index}")
    with pytest.raises(RunConcurrencyExceeded, match="workspace"):
        await spine.root(w1, "someone-new")

    await spine.root(w2, "someone-new")


async def test_concurrent_admission_admits_exactly_the_ceiling(spine: _Spine) -> None:
    w1, _ = _workspaces(spine)
    outcomes = await asyncio.gather(
        *(spine.root(w1, "alice") for _ in range(20)), return_exceptions=True
    )

    admitted = [item for item in outcomes if not isinstance(item, BaseException)]
    refused = [item for item in outcomes if isinstance(item, RunConcurrencyExceeded)]
    assert (len(admitted), len(refused)) == (8, 12)
    active = await spine.store.list_by_status(RunStatus.QUEUED, workspace_id=w1)
    assert len(active) == 8


async def test_concurrent_admission_across_workspaces_holds_the_principal_ceiling(
    spine: _Spine,
) -> None:
    w1, w2 = _workspaces(spine)
    outcomes = await asyncio.gather(
        *(spine.root(w1 if index % 2 else w2, "alice") for index in range(20)),
        return_exceptions=True,
    )

    assert sum(not isinstance(item, BaseException) for item in outcomes) == 8
    assert all(
        isinstance(item, RunConcurrencyExceeded)
        for item in outcomes
        if isinstance(item, BaseException)
    )


async def test_tightened_limits_are_what_the_store_enforces() -> None:
    from maistro.runs.consumer_claim import ClaimingInMemoryRunStore

    scope_store = InMemoryProjectScopeStore()
    projects = await _projects(scope_store, ("w1",))
    store = ClaimingInMemoryRunStore(
        project_store=scope_store,
        concurrency_limits=RunConcurrencyLimits(per_principal=1, per_workspace=2),
    )
    tight = _Spine(store, projects)

    await tight.root("w1", "alice")
    with pytest.raises(RunConcurrencyExceeded, match="principal"):
        await tight.root("w1", "alice")
    await tight.root("w1", "bob")
    with pytest.raises(RunConcurrencyExceeded, match="workspace"):
        await tight.root("w1", "carol")


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_the_spine_wiring_enforces_the_configured_settings(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shipped path: `wire_execution_spine` reads the operator's settings."""
    from maistro.config.settings import get_settings
    from maistro.runs.wiring import wire_execution_spine

    monkeypatch.setenv("MAX_ACTIVE_ROOT_RUNS_PER_PRINCIPAL", "2")
    get_settings.cache_clear()
    conn = await aiosqlite.connect(":memory:") if backend == "sqlite" else None
    try:
        projects, runs, *_rest = await wire_execution_spine(conn, workspace_id="w1")
        root = await projects.root_for_workspace("w1")
        wired = _Spine(runs, {"w1": root.project_id})
        await wired.root("w1", "alice")
        await wired.root("w1", "alice")
        with pytest.raises(RunConcurrencyExceeded) as refused:
            await wired.root("w1", "alice")
        assert refused.value.limit == 2
    finally:
        get_settings.cache_clear()
        if conn is not None:
            await conn.close()


def _occurrence(scheduled_for: str) -> dict[str, str]:
    return {
        ADMISSION_SOURCE: SCHEDULE_SOURCE,
        SCHEDULE_ID_KEY: "sched-1",
        SCHEDULED_FOR_KEY: scheduled_for,
    }


async def test_a_duplicate_occurrence_at_the_ceiling_is_refused_as_a_duplicate(
    spine: _Spine,
) -> None:
    """A second ticker retrying an admitted occurrence must see the duplicate,
    or it holds its cursor behind backpressure that is not its own."""
    w1, _ = _workspaces(spine)
    await spine.store.create_run(
        spine.graph(w1),
        actor_principal_id="alice",
        provenance=_occurrence("2026-09-26T00:00:00+00:00"),
        initial_status=RunStatus.QUEUED,
    )
    for _ in range(7):
        await spine.root(w1, "alice")

    with pytest.raises(DuplicateOccurrence):
        await spine.store.create_run(
            spine.graph(w1),
            actor_principal_id="alice",
            provenance=_occurrence("2026-09-26T00:00:00+00:00"),
            initial_status=RunStatus.QUEUED,
        )


async def test_a_refused_occurrence_is_admissible_once_a_slot_frees(spine: _Spine) -> None:
    """The refusal leaves no claim behind that would later read as a duplicate."""
    w1, _ = _workspaces(spine)
    admitted = [await spine.root(w1, "alice") for _ in range(8)]
    owed = _occurrence("2026-09-26T01:00:00+00:00")
    with pytest.raises(RunConcurrencyExceeded):
        await spine.store.create_run(spine.graph(w1), actor_principal_id="alice", provenance=owed)

    await spine.move(admitted[0].run_id, RunStatus.CANCELLED)

    run = await spine.store.create_run(spine.graph(w1), actor_principal_id="alice", provenance=owed)
    assert run.provenance[SCHEDULED_FOR_KEY] == owed[SCHEDULED_FOR_KEY]


async def test_a_sqlite_refusal_leaves_a_sibling_stores_open_write_intact() -> None:
    """The spine's SQLite connection is shared with sibling stores: a refusal
    must neither collide with their open transaction nor roll it back."""
    from maistro.runs.consumer_claim import ClaimingSqliteRunStore

    scope_store = InMemoryProjectScopeStore()
    projects = await _projects(scope_store, ("w1",))
    conn = await aiosqlite.connect(":memory:")
    try:
        store = ClaimingSqliteRunStore(
            conn,
            project_store=scope_store,
            concurrency_limits=RunConcurrencyLimits(per_principal=1),
        )
        await store.ensure_schema()
        await conn.execute("CREATE TABLE sibling (value TEXT)")
        await conn.commit()
        spine = _Spine(store, projects)
        await spine.root("w1", "alice")

        await conn.execute("INSERT INTO sibling VALUES ('uncommitted')")
        assert conn.in_transaction
        with pytest.raises(RunConcurrencyExceeded):
            await spine.root("w1", "alice")

        async with conn.execute("SELECT value FROM sibling") as cursor:
            assert await cursor.fetchall() == [("uncommitted",)]
    finally:
        await conn.close()


async def test_a_chat_turn_over_the_ceiling_is_refused_not_answered_unrecorded() -> None:
    """`Container._admit_chat_turn` swallows bookkeeping failures so a turn is
    still answered; backpressure is not one of them."""
    from types import SimpleNamespace

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    messages = [{"role": "user", "content": "hi"}]
    alice = SimpleNamespace(user_id="alice")
    for _ in range(8):
        assert await container._admit_chat_turn(messages, auth=alice) is not None

    with pytest.raises(RunConcurrencyExceeded):
        await container._admit_chat_turn(messages, auth=alice)
