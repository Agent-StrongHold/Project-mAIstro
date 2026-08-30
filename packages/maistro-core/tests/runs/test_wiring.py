"""The container and the server admit into the same, real spine (#41).

Wiring is where an execution-identity claim quietly becomes false: a store that
is durable in one process and ephemeral in another, or a Root Project resolved
lazily so the first submission is the one that discovers it does not exist.
These hold the wiring to producing three objects that agree with each other.
"""

from __future__ import annotations

from typing import Any

import aiosqlite
import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue


async def test_without_a_connection_the_spine_is_in_memory() -> None:
    (
        scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="w1")

    assert isinstance(scope_store, InMemoryProjectScopeStore)
    assert isinstance(run_store, InMemoryRunStore)
    assert admitter is not None


async def test_with_a_connection_the_spine_is_durable() -> None:
    async with aiosqlite.connect(":memory:") as conn:
        (
            scope_store,
            run_store,
            _admitter,
            _templates,
            _schedules,
            _continuations,
        ) = await wire_execution_spine(conn, workspace_id="w1")

        assert type(scope_store).__name__ == "SqliteProjectScopeStore"
        assert type(run_store).__name__ == "ClaimingSqliteRunStore"


async def test_the_root_project_exists_before_the_first_submission() -> None:
    """Resolved eagerly: a Run store refuses a Graph in a Project that isn't
    there, so a lazy root turns misconfiguration into a first-task failure."""
    (
        scope_store,
        _run_store,
        _admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="w1")

    root = await scope_store.root_for_workspace("w1")

    assert root.is_root


@pytest.mark.parametrize("durable", [False, True])
async def test_a_queue_on_the_wired_spine_admits_a_resolvable_run(durable: bool) -> None:
    """The claim that matters: the run_id a submission returns resolves in the
    same store the wiring handed back, in both backends."""
    conn = await aiosqlite.connect(":memory:") if durable else None
    try:
        (
            _scope_store,
            run_store,
            admitter,
            _templates,
            _schedules,
            _continuations,
        ) = await wire_execution_spine(conn, workspace_id="w1")
        queue = TaskQueue(admitter=admitter)

        task = await queue.submit(TaskCreate(description="ship it", task_type="code"))

        assert task.run_id
        run = await run_store.get_run(task.run_id)
        assert run is not None
        assert run.workspace_id == "w1"
    finally:
        if conn is not None:
            await conn.close()


async def test_the_workspace_is_the_one_asked_for() -> None:
    (
        _scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="tenant-a")
    queue = TaskQueue(admitter=admitter)

    task = await queue.submit(TaskCreate(description="ship it"))

    run = await run_store.get_run(task.run_id or "")
    assert run is not None
    assert run.workspace_id == "tenant-a"


# --- selecting the PostgreSQL spine (#132) ---------------------------------


async def test_a_pool_without_the_spine_tables_falls_back_and_says_so(caplog) -> None:
    """A caller-supplied pool has been through no preflight.

    Two paths reach `wire_execution_spine` with a pool and only one is checked.
    The URL path runs the container's schema preflight and refuses an unmigrated
    database by name, so the answer there is always yes. #135's seam — a caller
    that already holds a pool — guarantees nothing, and may legitimately hold
    only the tables it cared about: that is exactly what the `durable-events` CI
    job builds, a database with the event tables and nothing else.

    Assuming the spine is there turns that into `UndefinedTableError` raised
    from inside `create_container`, which is a startup crash for a deployment
    that never asked for a durable spine.

    The warning is the part that matters. A durable pool that ends up with an
    in-memory spine is the shape of #122, and the only thing separating this
    fallback from that defect is that this one says so.
    """
    import logging

    from maistro.runs.store import InMemoryRunStore
    from maistro.runs.wiring import wire_execution_spine

    class _PoolWithoutTheSpine:
        async def fetchval(self, _sql: str, _name: str) -> bool:
            return False

    with caplog.at_level(logging.WARNING):
        (
            _scope,
            run_store,
            _admitter,
            _templates,
            _schedules,
            _continuations,
        ) = await wire_execution_spine(None, workspace_id="w1", pg_pool=_PoolWithoutTheSpine())

    assert isinstance(run_store, InMemoryRunStore)
    assert "canonical_runs" in caplog.text
    assert "alembic upgrade head" in caplog.text


async def test_the_container_preflight_covers_the_spine_tables() -> None:
    """The URL path refuses rather than falling back, and names every table.

    Asserted against the constant the spine itself publishes, so adding a table
    to the spine cannot leave the startup check behind — which would put a real
    deployment on the fallback path above instead of telling it to migrate.
    """
    from maistro.container import _REQUIRED_PG_TABLES
    from maistro.runs.wiring import SPINE_PG_TABLES

    assert set(SPINE_PG_TABLES) <= set(_REQUIRED_PG_TABLES)


async def test_a_pool_without_the_schedules_table_falls_back_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from maistro.runs.wiring import _pg_schedule_store
    from maistro.scheduling.store import InMemoryScheduleStore

    class _PoolAtRevision015:
        async def fetchval(self, _sql: str, _name: str) -> bool:
            return False

    with caplog.at_level(logging.WARNING):
        schedules = await _pg_schedule_store(_PoolAtRevision015())

    assert isinstance(schedules, InMemoryScheduleStore)
    assert "schedules" in caplog.text
    assert "alembic upgrade head" in caplog.text


async def test_a_pool_without_the_node_templates_table_falls_back_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The branch a deployment between 019 and 020 actually takes (#556).

    Written and never executed, this would be a comment with a syntax — the
    same gap the diff-coverage gate found in #522's purge bound. So it is run:
    a pool whose database lacks the table gets a working in-process registry
    and a warning that says how to fix it, rather than an `UndefinedTableError`
    on the first `put`.
    """
    import logging

    from maistro.graph.templates import InMemoryNodeTemplateStore
    from maistro.runs.wiring import _pg_node_template_store

    class _PoolAtRevision019:
        async def fetchval(self, _sql: str, _name: str) -> bool:
            return False

    with caplog.at_level(logging.WARNING):
        templates = await _pg_node_template_store(_PoolAtRevision019())

    assert isinstance(templates, InMemoryNodeTemplateStore)
    assert "node_templates" in caplog.text
    assert "alembic upgrade head" in caplog.text


async def test_a_migrated_pool_gets_the_durable_node_template_store(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other side of it, and the reason the warning above is a warning:
    a migrated database must NOT be told to migrate."""
    import logging

    from maistro.graph.pg_templates import PgNodeTemplateStore
    from maistro.runs.wiring import _pg_node_template_store

    class _PoolAtRevision020:
        async def fetchval(self, _sql: str, _name: str) -> bool:
            return True

    with caplog.at_level(logging.WARNING):
        templates = await _pg_node_template_store(_PoolAtRevision020())

    assert isinstance(templates, PgNodeTemplateStore)
    assert "alembic upgrade head" not in caplog.text


def test_the_spine_preflight_does_not_demand_the_node_templates_table() -> None:
    """A database at `019` must not lose its Runs over a table it never had.

    The same reasoning `schedules` carries, asserted for the same reason: the
    tempting fix for a future "why aren't my NodeTemplates durable" is to add
    this table to that tuple, and that fix would drop every pre-020 deployment
    to an in-memory spine.
    """
    from maistro.runs.wiring import SPINE_PG_TABLES

    assert "node_templates" not in SPINE_PG_TABLES


def test_the_spine_preflight_does_not_demand_the_schedules_table() -> None:
    """A database at `015` must not lose its Runs over a table it never had.

    `schedules` is probed separately for exactly this reason: folding it into
    `SPINE_PG_TABLES` would drop every deployment migrated before #231 to an
    in-memory spine, which is a far worse failure than ephemeral schedules.
    Asserted rather than left to the comment, because the fix for a future
    "why isn't my schedule durable" is to add it to that tuple, and that fix
    would be wrong.
    """
    from maistro.runs.wiring import SPINE_PG_TABLES

    assert "schedules" not in SPINE_PG_TABLES


async def test_a_migrated_pool_gets_the_postgres_schedule_store(pg_pool: Any) -> None:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.runs.wiring import wire_execution_spine
    from maistro.scheduling.pg_store import PgScheduleStore

    _scope, _runs, _admitter, _templates, schedules, _continuations = await wire_execution_spine(
        None, workspace_id="w1", pg_pool=pg_pool
    )
    assert isinstance(schedules, PgScheduleStore)


async def test_without_a_pool_or_a_connection_schedules_are_in_memory() -> None:
    from maistro.runs.wiring import wire_execution_spine
    from maistro.scheduling.store import InMemoryScheduleStore

    _scope, _runs, _admitter, _templates, schedules, _continuations = await wire_execution_spine(
        None, workspace_id="w1"
    )
    assert isinstance(schedules, InMemoryScheduleStore)


async def test_a_pool_without_the_continuations_table_falls_back_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A deployment between 020 and 021 keeps its Runs and loses only durability
    of the traversal half (#44).

    Raising here would be worse than warning: the spine tables are present, so
    the Runs themselves are durable, and refusing to start over a table added
    later turns a partial migration into an outage. The warning is the part
    that matters -- a durable pool with in-memory continuations loses every
    paused HITL frontier on restart, and nothing else would say so.
    """
    import logging

    from maistro.graph.durable_runs.continuation import InMemoryGraphContinuationStore
    from maistro.runs.wiring import _pg_continuation_store

    class _PoolAtRevision020:
        async def fetchval(self, _sql: str, _name: str) -> bool:
            return False

    with caplog.at_level(logging.WARNING):
        continuations = await _pg_continuation_store(_PoolAtRevision020())

    assert isinstance(continuations, InMemoryGraphContinuationStore)
    assert "graph_continuations" in caplog.text
    assert "021" in caplog.text


async def test_a_migrated_pool_gets_the_durable_continuation_store(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other side of it, and the reason the warning above is a warning:
    a migrated database must NOT be told to migrate."""
    import logging

    from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore
    from maistro.runs.wiring import _pg_continuation_store

    class _PoolAtRevision021:
        async def fetchval(self, _sql: str, _name: str) -> bool:
            return True

    with caplog.at_level(logging.WARNING):
        continuations = await _pg_continuation_store(_PoolAtRevision021())

    assert isinstance(continuations, PgGraphContinuationStore)
    assert "alembic upgrade head" not in caplog.text


def test_the_spine_preflight_does_not_demand_the_continuations_table() -> None:
    """A database at `020` must not lose its Runs over a table it never had.

    The same reasoning `schedules` and `node_templates` carry, asserted for the
    same reason: the tempting fix for a future "why aren't my graph runs
    durable" is to add this table to that tuple, and that fix would drop every
    pre-021 deployment to an in-memory spine.
    """
    from maistro.runs.wiring import SPINE_PG_TABLES

    assert "graph_continuations" not in SPINE_PG_TABLES
