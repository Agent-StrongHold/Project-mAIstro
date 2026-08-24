"""The in-memory Run store is bounded (#122 review).

maistro-server creates one Run per submitted task and nothing else evicts them,
so an unbounded store is a process leak on any long-lived instance. `TaskQueue`
met the smaller version of this and answered it the same way; the Run store had
no answer at all.

The interesting property is *what* it evicts, not that it evicts: dropping a
live Run would delete the execution identity of work still running, which is
worse than the memory it reclaims.
"""

from __future__ import annotations

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore

KIND = "transform.format_markdown"


@pytest.fixture
async def scoped():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    return projects, root.project_id


def _graph(project_id: str) -> Graph:
    return Graph(
        workspace_id="w1",
        project_id=project_id,
        name="g",
        nodes=[Node(node_type=KIND, name="n")],
    )


async def _terminal_run(store: InMemoryRunStore, project_id: str) -> str:
    run = await store.create_run(_graph(project_id))
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.COMPLETED)
    return run.run_id


async def test_terminal_runs_are_evicted_oldest_first(scoped) -> None:
    projects, project_id = scoped
    store = InMemoryRunStore(project_store=projects, max_runs=4, prune_target=2)

    ids = [await _terminal_run(store, project_id) for _ in range(4)]
    await store.create_run(_graph(project_id))

    # Five runs, pruned down to the target of two: the three oldest terminal
    # ones go, the newest terminal one and the live one stay. Pruning to a
    # target rather than trimming one at a time is what keeps the cost amortised.
    assert len(store._runs) == 2
    assert [await store.get_run(run_id) for run_id in ids[:3]] == [None, None, None]
    assert await store.get_run(ids[3]) is not None


async def test_live_runs_are_never_evicted(scoped) -> None:
    """Evicting a running Run deletes the execution identity of work in flight."""
    projects, project_id = scoped
    store = InMemoryRunStore(project_store=projects, max_runs=2, prune_target=1)

    live = [(await store.create_run(_graph(project_id))).run_id for _ in range(3)]
    await store.create_run(_graph(project_id))

    for run_id in live:
        assert await store.get_run(run_id) is not None


async def test_a_store_of_only_live_runs_keeps_growing(scoped) -> None:
    """The correct failure: ten thousand unfinished Runs is a different problem
    and should look like one, not be silently papered over by eviction."""
    projects, project_id = scoped
    store = InMemoryRunStore(project_store=projects, max_runs=2, prune_target=1)

    for _ in range(5):
        await store.create_run(_graph(project_id))

    assert len(store._runs) == 5


async def test_node_runs_and_attempts_go_with_the_run(scoped) -> None:
    """Leaving them keeps the larger half of the memory and removes the index
    into it — a leak that is also unreachable."""
    projects, project_id = scoped
    store = InMemoryRunStore(project_store=projects, max_runs=2, prune_target=1)

    run = await store.create_run(_graph(project_id))
    node_run = await store.create_node_run(
        run.run_id, node_id=run.graph.materialize().nodes[0].node_id
    )
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.COMPLETED)

    for _ in range(3):
        await store.create_run(_graph(project_id))

    assert await store.get_run(run.run_id) is None
    assert await store.get_node_run(node_run.node_run_id) is None
    assert attempt.attempt_id not in store._attempts


async def test_an_incoherent_bound_is_refused(scoped) -> None:
    projects, _project_id = scoped

    with pytest.raises(ValueError, match="prune_target"):
        InMemoryRunStore(project_store=projects, max_runs=10, prune_target=20)


async def test_the_default_bound_does_not_disturb_ordinary_use(scoped) -> None:
    projects, project_id = scoped
    store = InMemoryRunStore(project_store=projects)

    ids = [await _terminal_run(store, project_id) for _ in range(5)]

    for run_id in ids:
        assert await store.get_run(run_id) is not None
