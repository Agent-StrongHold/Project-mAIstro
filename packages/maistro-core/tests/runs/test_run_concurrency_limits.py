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
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


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
        actor = principal if principal is not None else DEFAULT_TEST_ACTOR_PRINCIPAL_ID
        return await self.store.create_run(
            self.graph(workspace), actor_principal_id=actor, initial_status=RunStatus.QUEUED
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
        await spine.root(w1, f"user-{index % 8}")

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
        # Still the sibling's to finish: the refusal neither committed its
        # write nor ended its transaction, so its own rollback discards it.
        assert conn.in_transaction
        await conn.rollback()
        async with conn.execute("SELECT value FROM sibling") as cursor:
            assert await cursor.fetchall() == []
        async with conn.execute("SELECT COUNT(*) FROM canonical_runs") as cursor:
            assert await cursor.fetchone() == (1,)
    finally:
        await conn.close()


async def test_a_sqlite_refusal_with_no_open_transaction_leaves_none_open() -> None:
    """On its own, the refusal's savepoint is its whole transaction: releasing
    it must not leave the shared connection holding SQLite's write lock."""
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
        spine = _Spine(store, projects)
        admitted = await spine.root("w1", "alice")

        with pytest.raises(RunConcurrencyExceeded):
            await spine.root("w1", "alice")

        assert not conn.in_transaction
        async with conn.execute("SELECT run_id FROM canonical_runs") as cursor:
            assert await cursor.fetchall() == [(admitted.run_id,)]
    finally:
        await conn.close()


async def test_a_sqlite_count_that_fails_does_not_leave_its_row_for_the_next_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A root whose ceiling could not be read is not admitted: its savepoint is
    unwound, so the next writer's commit cannot persist it (review)."""
    import maistro.runs.sqlite_store as sqlite_store_module
    from maistro.runs.consumer_claim import ClaimingSqliteRunStore

    scope_store = InMemoryProjectScopeStore()
    projects = await _projects(scope_store, ("w1",))
    conn = await aiosqlite.connect(":memory:")
    try:
        store = ClaimingSqliteRunStore(conn, project_store=scope_store)
        await store.ensure_schema()
        spine = _Spine(store, projects)
        # The count seam is explicit now: `_admit_root` executes the module's
        # counts SQL on the connection it was handed. Naming a table the
        # schema does not have fails that one statement without touching any
        # other query the admission path runs.
        real_counts_sql = sqlite_store_module._ACTIVE_ROOT_COUNTS_SQL
        monkeypatch.setattr(
            sqlite_store_module,
            "_ACTIVE_ROOT_COUNTS_SQL",
            real_counts_sql.replace("canonical_runs", "canonical_runs_absent"),
        )
        with pytest.raises(aiosqlite.OperationalError, match="canonical_runs_absent"):
            await spine.root("w1", "alice")
        monkeypatch.setattr(sqlite_store_module, "_ACTIVE_ROOT_COUNTS_SQL", real_counts_sql)
        assert not conn.in_transaction

        admitted = await spine.root("w1", "alice")

        async with conn.execute("SELECT run_id FROM canonical_runs") as cursor:
            assert await cursor.fetchall() == [(admitted.run_id,)]
    finally:
        await conn.close()


async def test_sqlite_counts_read_the_active_root_indexes() -> None:
    """Both counts are served by partial indexes over the live roots, so
    admission does not scan every Run a long-lived database still holds."""
    from maistro.runs.sqlite_store import _ACTIVE_ROOT_COUNTS_SQL, SqliteRunStore

    conn = await aiosqlite.connect(":memory:")
    try:
        await SqliteRunStore(conn, project_store=InMemoryProjectScopeStore()).ensure_schema()
        async with conn.execute(
            f"EXPLAIN QUERY PLAN {_ACTIVE_ROOT_COUNTS_SQL}", ("w1", "alice")
        ) as cursor:
            plan = " ".join(str(row[3]) for row in await cursor.fetchall())
        assert "USING INDEX idx_canonical_runs_active_root_workspace" in plan
        assert "USING INDEX idx_canonical_runs_active_root_principal" in plan
    finally:
        await conn.close()


async def _store_and_supplied_connection(
    limits: RunConcurrencyLimits,
) -> tuple[_Spine, aiosqlite.Connection, aiosqlite.Connection]:
    """A real store on one connection, plus a second initialized connection.

    Two genuinely distinct `:memory:` databases, each carrying the full
    schema: a helper that reads the store's own connection when it was handed
    the other one must fail the tests below, which is exactly the evidence
    they exist to collect.
    """
    from maistro.runs.sqlite_store import SqliteRunStore

    scope_store = InMemoryProjectScopeStore()
    projects = await _projects(scope_store, ("w1",))
    store_conn = await aiosqlite.connect(":memory:")
    supplied = await aiosqlite.connect(":memory:")
    store = SqliteRunStore(store_conn, project_store=scope_store, concurrency_limits=limits)
    await store.ensure_schema()
    await SqliteRunStore(supplied, project_store=scope_store).ensure_schema()
    for conn in (store_conn, supplied):
        await conn.execute("CREATE TABLE sibling (value TEXT)")
        await conn.commit()
    return _Spine(store, projects), store_conn, supplied


def _root_run(spine: _Spine, workspace: str, principal: str) -> Any:
    """A root Run the way `create_run` would build it, before its insert."""
    from maistro.runs.model import GraphSnapshot, Run

    return Run(
        workspace_id=workspace,
        project_id=spine.projects[workspace],
        graph=GraphSnapshot.from_graph(spine.graph(workspace)),
        actor_principal_id=principal,
        status=RunStatus.QUEUED,
    )


async def _insert_candidate(run: Any, conn: aiosqlite.Connection) -> None:
    """The candidate's row, written exactly as `create_run` writes it."""
    from maistro.runs.evidence_json import json_of

    await conn.execute(
        """INSERT INTO canonical_runs
           (run_id, workspace_id, project_id, parent_run_id,
            parent_node_run_id, status, payload)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            run.run_id,
            run.workspace_id,
            run.project_id,
            run.parent_run_id,
            run.parent_node_run_id,
            run.status.value,
            json_of(run),
        ),
    )


async def test_sqlite_root_helper_counts_on_supplied_connection() -> None:
    """`_admit_root` counts on the connection its caller supplies.

    The supplied connection already holds an active root the store's own
    connection cannot see, so the candidate exceeds the workspace ceiling
    there while counting zero on the store's connection. The savepoint is
    established on the supplied connection before the candidate is inserted,
    matching `create_run`'s order. Connection-selection evidence for the
    reusable helper boundary, not a multi-writer architecture proposal: a
    helper that read the store's connection would admit instead of refusing.
    """
    from maistro.runs.sqlite_store import _ROOT_ADMISSION_SAVEPOINT

    spine, store_conn, supplied = await _store_and_supplied_connection(
        RunConcurrencyLimits(per_principal=8, per_workspace=1)
    )
    try:
        await supplied.execute(
            """INSERT INTO canonical_runs
               (run_id, workspace_id, project_id, parent_run_id,
                parent_node_run_id, status, payload)
               VALUES ('occupant-1', 'w1', ?, NULL, NULL, ?, '{}')""",
            (spine.projects["w1"], RunStatus.QUEUED.value),
        )
        candidate = _root_run(spine, "w1", "alice")
        await supplied.execute(f"SAVEPOINT {_ROOT_ADMISSION_SAVEPOINT}")
        await _insert_candidate(candidate, supplied)

        with pytest.raises(RunConcurrencyExceeded) as refused:
            await spine.store._admit_root(candidate, connection=supplied)  # type: ignore[arg-type]

        assert (refused.value.scope, refused.value.limit, refused.value.active) == (
            "workspace",
            1,
            1,
        )
    finally:
        await store_conn.close()
        await supplied.close()


async def test_sqlite_root_helper_refusal_rolls_back_only_supplied_savepoint() -> None:
    """A refusal unwinds exactly the supplied connection's savepoint.

    Controlled sentinel writes sit open on both connections. The refusal must
    undo the candidate row alone: the writes each transaction already owned
    survive, both connections stay inside their test-owned transactions (no
    helper commit), and the savepoint is released, not merely rolled back. A
    helper that cleaned up the store's connection would fail here -- it would
    find no savepoint and raise, not refuse.
    """
    from maistro.runs.sqlite_store import _ROOT_ADMISSION_SAVEPOINT

    spine, store_conn, supplied = await _store_and_supplied_connection(
        RunConcurrencyLimits(per_principal=8, per_workspace=1)
    )
    try:
        await store_conn.execute("INSERT INTO sibling VALUES ('store-owned')")
        await supplied.execute("INSERT INTO sibling VALUES ('supplied-owned')")
        await supplied.execute(
            """INSERT INTO canonical_runs
               (run_id, workspace_id, project_id, parent_run_id,
                parent_node_run_id, status, payload)
               VALUES ('occupant-1', 'w1', ?, NULL, NULL, ?, '{}')""",
            (spine.projects["w1"], RunStatus.QUEUED.value),
        )
        candidate = _root_run(spine, "w1", "alice")
        await supplied.execute(f"SAVEPOINT {_ROOT_ADMISSION_SAVEPOINT}")
        await _insert_candidate(candidate, supplied)

        with pytest.raises(RunConcurrencyExceeded):
            await spine.store._admit_root(candidate, connection=supplied)  # type: ignore[arg-type]

        async with supplied.execute("SELECT run_id FROM canonical_runs") as cursor:
            assert await cursor.fetchall() == [("occupant-1",)]
        assert supplied.in_transaction
        assert store_conn.in_transaction
        async with supplied.execute("SELECT value FROM sibling") as cursor:
            assert await cursor.fetchall() == [("supplied-owned",)]
        async with store_conn.execute("SELECT value FROM sibling") as cursor:
            assert await cursor.fetchall() == [("store-owned",)]
        # RELEASE, not only ROLLBACK: nothing is left for the next writer to
        # trip over.
        with pytest.raises(aiosqlite.OperationalError, match="no such savepoint"):
            await supplied.execute(f"ROLLBACK TO SAVEPOINT {_ROOT_ADMISSION_SAVEPOINT}")
    finally:
        await store_conn.close()
        await supplied.close()


async def test_sqlite_count_read_failure_rolls_back_only_supplied_savepoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A count that cannot be read is cleaned up like a refusal: through the
    supplied connection's savepoint, leaving every other write owned."""
    import maistro.runs.sqlite_store as sqlite_store_module
    from maistro.runs.sqlite_store import _ROOT_ADMISSION_SAVEPOINT

    spine, store_conn, supplied = await _store_and_supplied_connection(RunConcurrencyLimits())
    try:
        await store_conn.execute("INSERT INTO sibling VALUES ('store-owned')")
        await supplied.execute("INSERT INTO sibling VALUES ('supplied-owned')")
        candidate = _root_run(spine, "w1", "alice")
        await supplied.execute(f"SAVEPOINT {_ROOT_ADMISSION_SAVEPOINT}")
        await _insert_candidate(candidate, supplied)

        real_counts_sql = sqlite_store_module._ACTIVE_ROOT_COUNTS_SQL
        monkeypatch.setattr(
            sqlite_store_module,
            "_ACTIVE_ROOT_COUNTS_SQL",
            real_counts_sql.replace("canonical_runs", "canonical_runs_absent"),
        )
        with pytest.raises(aiosqlite.OperationalError, match="canonical_runs_absent"):
            await spine.store._admit_root(candidate, connection=supplied)  # type: ignore[arg-type]
        monkeypatch.setattr(sqlite_store_module, "_ACTIVE_ROOT_COUNTS_SQL", real_counts_sql)

        async with supplied.execute("SELECT run_id FROM canonical_runs") as cursor:
            assert await cursor.fetchall() == []
        assert supplied.in_transaction
        assert store_conn.in_transaction
        async with supplied.execute("SELECT value FROM sibling") as cursor:
            assert await cursor.fetchall() == [("supplied-owned",)]
        async with store_conn.execute("SELECT value FROM sibling") as cursor:
            assert await cursor.fetchall() == [("store-owned",)]
    finally:
        await store_conn.close()
        await supplied.close()


async def test_sqlite_count_cancellation_still_unwinds_the_supplied_savepoint() -> None:
    """Cancellation hits the same `except BaseException` cleanup: the supplied
    savepoint is rolled back and released, in that order, and the original
    exception identity propagates. No new cancellation semantics are decided
    here -- no shielding, no task machinery -- only the cleanup this helper
    already owned, on the connection it was handed.
    """
    from maistro.runs.sqlite_store import _ROOT_ADMISSION_SAVEPOINT

    spine, store_conn, supplied = await _store_and_supplied_connection(RunConcurrencyLimits())
    executed: list[str] = []

    class _CountCancelled:
        """Delegates everything to the real connection but the count, which is
        cancelled the moment it executes -- the first statement the helper
        runs through its supplied connection in this flow."""

        def __init__(self, inner: aiosqlite.Connection) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        async def execute(self, query: str, parameters: Any = None) -> Any:
            if "COUNT(*)" in query:
                executed.append(" ".join(query.split())[:60])
                raise asyncio.CancelledError
            executed.append(" ".join(query.split())[:60])
            return await self._inner.execute(query, parameters)

    try:
        await supplied.execute("INSERT INTO sibling VALUES ('supplied-owned')")
        candidate = _root_run(spine, "w1", "alice")
        await supplied.execute(f"SAVEPOINT {_ROOT_ADMISSION_SAVEPOINT}")
        await _insert_candidate(candidate, supplied)

        with pytest.raises(asyncio.CancelledError):
            await spine.store._admit_root(  # type: ignore[arg-type]
                candidate, connection=_CountCancelled(supplied)
            )

        assert len(executed) == 3
        assert "COUNT(*)" in executed[0]
        assert executed[1].startswith("ROLLBACK TO SAVEPOINT canonical_root_run_admission")
        assert executed[2].startswith("RELEASE SAVEPOINT canonical_root_run_admission")
        async with supplied.execute("SELECT run_id FROM canonical_runs") as cursor:
            assert await cursor.fetchall() == []
        assert supplied.in_transaction
    finally:
        await store_conn.close()
        await supplied.close()


async def test_sqlite_create_run_supplies_existing_connection_to_root_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real public caller passes its own connection, exactly once, and the
    real helper still runs against it."""
    from maistro.runs.sqlite_store import SqliteRunStore

    scope_store = InMemoryProjectScopeStore()
    projects = await _projects(scope_store, ("w1",))
    conn = await aiosqlite.connect(":memory:")
    try:
        store = SqliteRunStore(conn, project_store=scope_store)
        await store.ensure_schema()
        spine = _Spine(store, projects)
        real_admit = store._admit_root
        supplied: list[Any] = []

        async def _spy(run: Any, *, connection: Any) -> None:
            supplied.append(connection)
            await real_admit(run, connection=connection)

        monkeypatch.setattr(store, "_admit_root", _spy)
        admitted = await spine.root("w1", "alice")

        assert len(supplied) == 1
        assert supplied[0] is conn
        async with conn.execute("SELECT run_id FROM canonical_runs") as cursor:
            assert await cursor.fetchall() == [(admitted.run_id,)]
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


async def test_a_full_ceiling_of_stranded_chat_turns_is_reclaimed_not_permanent() -> None:
    """Turns a crashed process left mid-admission hold slots no successful
    admission will ever free; the refused turn reclaims them and is admitted."""
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    messages = [{"role": "user", "content": "hi"}]
    alice = SimpleNamespace(user_id="alice")
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    stranded = []
    for _ in range(8):
        run = await container.chat_admitter.admit(messages, actor_principal_id="alice")  # type: ignore[union-attr]
        await container.run_store.transition_run(run.run_id, RunStatus.QUEUED, at=long_ago)
        stranded.append(run.run_id)

    admitted = await container._admit_chat_turn(messages, auth=alice)

    assert admitted.status is RunStatus.RUNNING
    for run_id in stranded:
        run = await container.run_store.get_run(run_id)
        assert run is not None
        assert run.status is RunStatus.CANCELLED


async def test_a_failed_reclamation_leaves_the_refusal_standing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery is housekeeping: when it cannot run, the turn is refused as
    backpressure rather than answered past the ceiling."""
    from types import SimpleNamespace

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    messages = [{"role": "user", "content": "hi"}]
    alice = SimpleNamespace(user_id="alice")
    for _ in range(8):
        await container._admit_chat_turn(messages, auth=alice)

    async def _broken(**_: object) -> int:
        raise RuntimeError("recovery store down")

    monkeypatch.setattr(container, "_recover_stranded_chat_runs", _broken)
    with pytest.raises(RunConcurrencyExceeded):
        await container._admit_chat_turn(messages, auth=alice)
