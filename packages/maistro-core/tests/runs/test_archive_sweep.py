"""The archive sweep, and the line it must not cross (#273, f436 decision 10).

The property worth testing here is not "cold Runs get archived" — it is that
*archiving and purging select disjoint populations*. ADR-082226-f436 decision 2
says a record whose identity nothing needs is deleted rather than archived, and
"archiving is not a way to avoid deciding that". The obvious implementation
hooks the archive into `purge_expired_runs`, which would quietly convert a
deletion decision into a storage one; the test that would fail is
`test_a_run_with_a_deletion_date_is_never_archived`.

Against a real `FilesystemArchiveStore` rather than a fake: the sweep's job is
to put bytes somewhere they can be read back, and a fake that records calls
proves the call was made with arguments the test already knew.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.archive.filesystem import FilesystemArchiveStore
from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import DEFAULT_ARCHIVE_AFTER, InMemoryRunStore

NOW = datetime(2026, 8, 25, tzinfo=UTC)
COLD = NOW - timedelta(days=200)
RECENT = NOW - timedelta(days=2)


@pytest.fixture
async def spine(tmp_path: Any) -> Any:
    """A store with the tier on, its archive, and a Project to file Runs in."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    project = await projects.create(
        workspace_id="workspace-1", parent_project_id=root.project_id, name="Cold"
    )
    archive = FilesystemArchiveStore(str(tmp_path))
    store = InMemoryRunStore(project_store=projects, archive_store=archive)
    graph = Graph(
        workspace_id="workspace-1",
        project_id=project.project_id,
        name="graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    return store, archive, graph, project.project_id


async def _run(spine: Any, *, status: RunStatus, finished: Any, retention: Any) -> Any:
    """A Run in a state the sweep will judge.

    Built through `create_run` and then moved, rather than constructed by hand:
    the model validates on the way in, so a state this helper can produce is a
    state the store can really hold.
    """
    store, _archive, graph, _project_id = spine
    run = await store.create_run(graph)
    moved = run.model_copy(
        update={"status": status, "finished_at": finished, "retention_expires_at": retention}
    )
    store._runs[run.run_id] = moved
    return moved


async def _keys(archive: FilesystemArchiveStore, scope: str) -> list[Any]:
    return [key async for key in archive.list_scope(scope)]


async def test_the_tier_is_off_without_an_archive_store() -> None:
    """f436 decision 9. Off is today's behaviour, not a degraded mode."""
    projects = InMemoryProjectScopeStore()
    await projects.create_root("workspace-1")
    store = InMemoryRunStore(project_store=projects)
    assert await store.archive_cold_runs(now=NOW) == 0


async def test_a_cold_run_kept_indefinitely_is_archived(spine: Any) -> None:
    store, archive, _graph, project_id = spine
    await _run(spine, status=RunStatus.COMPLETED, finished=COLD, retention=None)

    assert await store.archive_cold_runs(now=NOW) == 1
    assert len(await _keys(archive, project_id)) == 1


async def test_a_run_with_a_deletion_date_is_never_archived(spine: Any) -> None:
    """The line decision 2 draws, and the test that fails if anyone hooks the
    archive into `purge_expired_runs`.

    This Run is cold by every other measure. What disqualifies it is that
    somebody chose a date to delete it on, which makes it purge-eligible — and
    archiving it would turn that deletion decision into a storage one.
    """
    store, archive, _graph, project_id = spine
    await _run(spine, status=RunStatus.COMPLETED, finished=COLD, retention=NOW)

    assert await store.archive_cold_runs(now=NOW) == 0
    assert await _keys(archive, project_id) == []


async def test_a_recent_run_is_not_archived(spine: Any) -> None:
    store, _archive, _graph, _project_id = spine
    await _run(spine, status=RunStatus.COMPLETED, finished=RECENT, retention=None)
    assert await store.archive_cold_runs(now=NOW) == 0


async def test_live_work_is_not_archived(spine: Any) -> None:
    """A Run still running keeps its payload where it can be read without a
    network round trip, for the same reason retention never purges live work."""
    store, _archive, _graph, _project_id = spine
    await _run(spine, status=RunStatus.RUNNING, finished=None, retention=None)
    assert await store.archive_cold_runs(now=NOW) == 0


async def test_the_archived_bytes_are_the_run(spine: Any) -> None:
    """Round-trip, not just "something was written"."""
    store, archive, _graph, project_id = spine
    run = await _run(spine, status=RunStatus.COMPLETED, finished=COLD, retention=None)

    await store.archive_cold_runs(now=NOW)
    (key,) = await _keys(archive, project_id)
    payload = json.loads(await archive.get(key))

    assert payload["run_id"] == run.run_id
    assert payload["project_id"] == project_id
    assert payload["graph"]["graph_id"] == run.graph.graph_id


async def test_a_read_after_archiving_still_returns_the_run(spine: Any) -> None:
    """f436 decision 6: never an empty result for a record that exists.

    A silent `None` here is indistinguishable from deletion by every caller,
    which would turn a cost optimisation into data loss at the API boundary.
    """
    store, _archive, _graph, _project_id = spine
    run = await _run(spine, status=RunStatus.COMPLETED, finished=COLD, retention=None)

    await store.archive_cold_runs(now=NOW)

    found = await store.get_run(run.run_id)
    assert found is not None, "archiving must not make a Run unreadable"
    assert found.run_id == run.run_id


async def test_the_batch_limit_is_respected(spine: Any) -> None:
    """Sweeping is opportunistic: a backlog drains over several sweeps rather
    than one unbounded transaction."""
    store, archive, _graph, project_id = spine
    for _ in range(3):
        await _run(spine, status=RunStatus.COMPLETED, finished=COLD, retention=None)

    assert await store.archive_cold_runs(now=NOW, limit=2) == 2
    assert len(await _keys(archive, project_id)) == 2


async def test_a_non_positive_limit_is_refused(spine: Any) -> None:
    store, _archive, _graph, _project_id = spine
    with pytest.raises(ValueError, match="limit must be positive"):
        await store.archive_cold_runs(now=NOW, limit=0)


async def test_the_horizon_is_a_parameter_not_a_constant(spine: Any) -> None:
    """f436 open question 1 declined to freeze a number; decision 10 leaves the
    horizon to the operator. A Run too recent for the default is archivable
    under a shorter one."""
    store, _archive, _graph, _project_id = spine
    await _run(spine, status=RunStatus.COMPLETED, finished=RECENT, retention=None)

    assert await store.archive_cold_runs(now=NOW, archive_after=DEFAULT_ARCHIVE_AFTER) == 0
    assert await store.archive_cold_runs(now=NOW, archive_after=timedelta(days=1)) == 1


async def test_a_run_is_not_archived_twice(spine: Any) -> None:
    """The tombstone, without which the count lies.

    `PgRunStore` selects candidates with `archive_key IS NULL`; this store
    keeps the same record in a dict. The `put` is idempotent either way — keys
    are content-addressed, so re-archiving writes the same object — but a sweep
    that reported the same Run as newly archived on every pass would make the
    return value useless for deciding whether a backlog is draining.
    """
    store, archive, _graph, project_id = spine
    await _run(spine, status=RunStatus.COMPLETED, finished=COLD, retention=None)

    assert await store.archive_cold_runs(now=NOW) == 1
    assert await store.archive_cold_runs(now=NOW) == 0
    assert len(await _keys(archive, project_id)) == 1


async def test_a_terminal_run_with_no_finish_time_is_not_archived(spine: Any) -> None:
    """A state the model forbids and a row can still hold.

    `Run` validates that a terminal Run has a `finished_at`, but `model_copy`
    skips validation and so does a row hand-built by a migration or an older
    writer. The sweep's own check is what keeps that from becoming
    `None <= datetime`, which is a TypeError raised from inside housekeeping
    rather than a Run quietly left where it is.
    """
    store, archive, _graph, project_id = spine
    await _run(spine, status=RunStatus.COMPLETED, finished=None, retention=None)

    assert await store.archive_cold_runs(now=NOW) == 0
    assert await _keys(archive, project_id) == []
