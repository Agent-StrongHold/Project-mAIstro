"""`non_terminal_run_stats` answers the same way on all three backends (#338).

The metric #338's DoD asks for is current state derived from the store, so it
is only as good as the store that derives it. In-memory agreement proves the
shape; it does not prove the SQL. The PostgreSQL and SQLite legs both compute
the oldest `created_at` with a MIN over an ISO-8601 string inside the payload —
a shortcut that is correct only because that format sorts lexically in the same
order the datetimes do, which is exactly the kind of assumption worth pinning
against a real database rather than reasoning about.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs.model import RunStatus


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="stats",
        nodes=[Node(node_id="n1", node_type="agent")],
    )


async def test_an_empty_store_reports_nothing_open(spine: Any) -> None:
    store, _workspace, _project_id = spine

    assert await store.non_terminal_run_stats() == (0, None)


async def test_open_runs_are_counted_and_the_oldest_is_returned(spine: Any) -> None:
    """The oldest, not the newest and not an arbitrary row — the age gauge is
    only meaningful if it tracks the longest-waiting Run."""
    store, workspace, project_id = spine
    graph = _graph(workspace, project_id)

    first = await store.create_run(graph)
    second = await store.create_run(graph)

    count, oldest = await store.non_terminal_run_stats()

    assert count == 2
    assert oldest is not None
    # Tolerant of storage precision, strict about which Run it identified.
    assert abs((oldest - first.created_at).total_seconds()) < 1
    assert oldest <= second.created_at


@pytest.mark.parametrize("terminal", [RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED])
async def test_a_terminal_run_leaves_the_recoverable_set(spine: Any, terminal: RunStatus) -> None:
    """Every terminal status, not just the one the compensation path uses:
    the gauge's whole value is that it comes back down, whichever way a Run
    finished."""
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id))
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    if terminal is not RunStatus.CANCELLED:
        await store.transition_run(run.run_id, RunStatus.RUNNING)
    assert (await store.non_terminal_run_stats())[0] == 1

    await store.transition_run(run.run_id, terminal)

    assert await store.non_terminal_run_stats() == (0, None)


async def test_the_oldest_moves_forward_as_older_runs_settle(spine: Any) -> None:
    """Settling the longest-waiting Run must advance the age, not freeze it —
    a MIN taken over the wrong rows would keep reporting the settled one."""
    store, workspace, project_id = spine
    graph = _graph(workspace, project_id)
    first = await store.create_run(graph)
    second = await store.create_run(graph)

    await store.transition_run(first.run_id, RunStatus.CANCELLED)

    count, oldest = await store.non_terminal_run_stats()

    assert count == 1
    assert oldest is not None
    assert abs((oldest - second.created_at).total_seconds()) < 1


async def test_the_timestamp_is_comparable_to_a_live_clock(spine: Any) -> None:
    """The container subtracts this from `now` to get an age, so it has to come
    back timezone-aware on every backend — a naive datetime would raise there,
    and only against a real store would that show up."""
    from datetime import UTC, datetime

    store, workspace, project_id = spine
    await store.create_run(_graph(workspace, project_id))

    _, oldest = await store.non_terminal_run_stats()

    assert oldest is not None
    assert oldest.tzinfo is not None
    assert (datetime.now(UTC) + timedelta(seconds=5)) > oldest
