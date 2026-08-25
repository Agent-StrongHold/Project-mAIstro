"""I31: PostgreSQL canonical RunStore — property tests against the real store (#132).

The ordinary spine conformance suite proves fixed examples across memory,
SQLite, and PostgreSQL. These properties explore generated lifecycle sequences
and generated concurrent worker counts against the PostgreSQL implementation
itself. They skip when no PostgreSQL DSN exists; CI's PostgreSQL legs set the
DSN and run this module explicitly after migrations.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable
from typing import Any, TypeVar

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import ActiveAttemptExists, InMemoryRunStore

T = TypeVar("T")


def _run(coro: Awaitable[T]) -> T:
    return asyncio.run(coro)


def _dsn() -> str:
    return os.environ.get("MAISTRO_TEST_PG_DSN", "")


async def _pg_spine() -> tuple[Any, str, str, Any]:
    dsn = _dsn()
    if not dsn:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    asyncpg = pytest.importorskip("asyncpg")

    from maistro.persistence import _register_json_codecs
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=12, init=_register_json_codecs)
    workspace = f"formal-pg-{uuid.uuid4().hex}"
    projects = PgProjectScopeStore(pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name="Formal PostgreSQL spine",
    )
    return PgRunStore(pool, project_store=projects), workspace, project.project_id, pool


async def _memory_spine() -> tuple[InMemoryRunStore, str, str]:
    workspace = f"formal-memory-{uuid.uuid4().hex}"
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name="Formal memory spine",
    )
    return InMemoryRunStore(project_store=projects), workspace, project.project_id


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Formal lifecycle graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _transition_result(store: Any, run_id: str, target: RunStatus) -> tuple[str, str]:
    try:
        run = await store.transition_run(run_id, target)
    except Exception as exc:  # property compares the stores' public refusal semantics
        return "error", type(exc).__name__
    return "ok", run.status.value


@given(
    targets=st.lists(
        st.sampled_from(tuple(RunStatus)),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=20, deadline=60_000)
def test_postgres_run_transitions_match_the_reference_store(targets: list[RunStatus]) -> None:
    """For arbitrary transition sequences PostgreSQL accepts/refuses exactly
    what the in-memory reference store does, and persists the same final state.
    """

    async def exercise() -> None:
        pg, pg_workspace, pg_project, pool = await _pg_spine()
        memory, memory_workspace, memory_project = await _memory_spine()
        try:
            pg_run = await pg.create_run(_graph(pg_workspace, pg_project))
            memory_run = await memory.create_run(_graph(memory_workspace, memory_project))

            for target in targets:
                pg_result = await _transition_result(pg, pg_run.run_id, target)
                memory_result = await _transition_result(memory, memory_run.run_id, target)
                assert pg_result == memory_result

            persisted = await pg.get_run(pg_run.run_id)
            reference = await memory.get_run(memory_run.run_id)
            assert persisted is not None and reference is not None
            assert persisted.status is reference.status
        finally:
            await pool.close()

    _run(exercise())


@given(worker_count=st.integers(min_value=2, max_value=12))
@settings(max_examples=12, deadline=60_000)
def test_postgres_never_admits_two_active_attempts(worker_count: int) -> None:
    """Any generated number of simultaneous workers leaves one active Attempt.

    This is the PostgreSQL-specific invariant SQLite's single-writer behavior
    cannot prove: the database constraint and store error translation must hold
    under actual concurrent inserts.
    """

    async def exercise() -> None:
        store, workspace, project_id, pool = await _pg_spine()
        try:
            run = await store.create_run(_graph(workspace, project_id))
            node_run = await store.create_node_run(run.run_id, node_id="node-1")
            results = await asyncio.gather(
                *(
                    store.create_attempt(node_run.node_run_id, lease_holder=f"worker-{index}")
                    for index in range(worker_count)
                ),
                return_exceptions=True,
            )

            started = [item for item in results if not isinstance(item, BaseException)]
            refused = [item for item in results if isinstance(item, ActiveAttemptExists)]
            unexpected = [
                item
                for item in results
                if isinstance(item, BaseException) and not isinstance(item, ActiveAttemptExists)
            ]
            assert unexpected == []
            assert len(started) == 1
            assert len(refused) == worker_count - 1

            attempts = await store.list_attempts(node_run.node_run_id)
            active = [
                attempt
                for attempt in attempts
                if attempt.status in (AttemptStatus.CREATED, AttemptStatus.RUNNING)
            ]
            assert len(active) == 1
        finally:
            await pool.close()

    _run(exercise())
