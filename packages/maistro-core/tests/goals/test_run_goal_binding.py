"""Run admission binds `goal_id`/`goal_revision` as immutable provenance.

The Goal store (#1572) is only half of the binding contract; the other half is
on the spine: a Run can name the Goal and the exact desired-state revision it
was admitted against, and after admission nothing can move that binding — a
historical Run keeps the revision it used even as the Goal moves on.

These tests drive the shipped admission seam (`admit_direct_work`) over the
in-memory reference store and the SQLite durable twin, because the binding is
payload-carried on both backends and the round-trip through storage is the
part a pure-model test would not prove.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.goals import GoalRevisionDraft, GoalStatus, InMemoryGoalStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import RunStatus
from maistro.runs.admission import admit_direct_work
from maistro.runs.model import Run
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import InMemoryRunStore

KIND = "transform.format_markdown"
WORKSPACE = "ws-goal-binding"


async def _projects() -> tuple[InMemoryProjectScopeStore, str]:
    """A scope tree with the child Project admission files work under."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    project = await projects.create(
        workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Goals"
    )
    return projects, project.project_id


@pytest.fixture(params=["memory", "sqlite"])
async def run_spine(request, tmp_path) -> Any:
    """A Run store on one of its two non-PostgreSQL backends, plus the ids
    admission needs. PostgreSQL rides the same payload round-trip (the same
    `json_of` write and `model_validate` read), and is covered by the
    runs-store conformance suite; these legs prove the binding contract
    itself, which the payload carries identically."""
    projects, project_id = await _projects()
    if request.param == "memory":
        yield InMemoryRunStore(project_store=projects), project_id, None
        return
    import aiosqlite

    conn = await aiosqlite.connect(tmp_path / "runs.db")
    store = SqliteRunStore(conn, project_store=projects)
    await store.ensure_schema()
    try:
        yield store, project_id, conn
    finally:
        await conn.close()


async def _admit(store, project_id: str, **overrides: Any) -> Run:
    kwargs: dict[str, Any] = {
        "workspace_id": WORKSPACE,
        "project_id": project_id,
        "node_type": KIND,
        "name": "do the thing",
        "source": "test",
        "actor_principal_id": "alice",
    }
    kwargs.update(overrides)
    return await admit_direct_work(store, **kwargs)


async def test_admission_binds_goal_id_and_revision(run_spine) -> None:
    store, project_id, conn = run_spine
    run = await _admit(store, project_id, goal_id="goal-1", goal_revision=3)
    assert (run.goal_id, run.goal_revision) == ("goal-1", 3)
    if conn is not None:
        await conn.commit()
    read_back = await store.get_run(run.run_id)
    assert read_back is not None
    assert (read_back.goal_id, read_back.goal_revision) == ("goal-1", 3), (
        "the binding survives storage, not just the in-hand model"
    )


async def test_the_binding_is_immutable_after_admission(run_spine) -> None:
    """Transitions to terminal never move the binding: a historical Run keeps
    the revision it was admitted against."""
    store, project_id, _ = run_spine
    run = await _admit(store, project_id, goal_id="goal-1", goal_revision=2)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.COMPLETED, result={"done": True})
    finished = await store.get_run(run.run_id)
    assert finished.status is RunStatus.COMPLETED
    assert (finished.goal_id, finished.goal_revision) == ("goal-1", 2)


async def test_admission_without_a_goal_leaves_the_binding_unset(run_spine) -> None:
    store, project_id, _ = run_spine
    run = await _admit(store, project_id)
    assert run.goal_id is None and run.goal_revision is None
    read_back = await store.get_run(run.run_id)
    assert read_back.goal_id is None and read_back.goal_revision is None


def _run(**overrides: Any) -> Run:
    from maistro.graph.definitions import Graph, Node
    from maistro.runs.model import GraphSnapshot

    fields: dict[str, Any] = {
        "workspace_id": WORKSPACE,
        "project_id": "prj-1",
        "actor_principal_id": "alice",
        "graph": GraphSnapshot.from_graph(
            Graph(
                workspace_id=WORKSPACE,
                project_id="prj-1",
                name="n",
                nodes=[Node(node_type=KIND, name="n")],
                edges=[],
            )
        ),
    }
    fields.update(overrides)
    return Run(**fields)


async def test_a_half_binding_is_refused() -> None:
    """`goal_id` without `goal_revision` — or the inverse — is not a binding;
    it is a typo that would read as provenance while naming nothing."""
    with pytest.raises(ValueError, match="paired"):
        _run(goal_id="goal-1")
    with pytest.raises(ValueError, match="paired"):
        _run(goal_revision=2)
    with pytest.raises(ValueError, match="non-empty"):
        _run(goal_id="   ", goal_revision=1)


async def test_a_run_outcome_never_moves_goal_state() -> None:
    """The spine has no path from a Run's outcome to the Goal's lifecycle.

    #1572: "A Run's outcome never sets Goal state implicitly." There is no
    callback to intercept — the guarantee is structural, a property of what
    the seam exposes — so this test does the next best thing: it drives a Run
    bound to a Goal to a terminal state and shows the Goal exactly where an
    explicit decision left it, with no transition record, then exercises the
    one public writer of Goal state to show the explicit path works.
    """
    projects, project_id = await _projects()
    goals = InMemoryGoalStore()
    goal = await goals.create_goal(
        workspace_id=WORKSPACE,
        project_id=project_id,
        agent_id="agent-7",
        draft=GoalRevisionDraft(desired_state="the thing is done", author="alice"),
    )
    store = InMemoryRunStore(project_store=projects)
    run = await admit_direct_work(
        store,
        workspace_id=WORKSPACE,
        project_id=project_id,
        node_type=KIND,
        name="work toward the goal",
        source="test",
        actor_principal_id="alice",
        goal_id=goal.goal_id,
        goal_revision=goal.current_revision,
    )
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.COMPLETED, result="done")
    unchanged = await goals.get_goal(goal.goal_id)
    assert unchanged.status is GoalStatus.ACTIVE
    assert await goals.list_goal_transitions(goal.goal_id) == []

    # The explicit path: a principal decides, and only then does the Goal move.
    await goals.transition_goal(
        goal.goal_id, GoalStatus.SATISFIED, expected_revision=1, actor="alice"
    )
    assert (await goals.get_goal(goal.goal_id)).status is GoalStatus.SATISFIED
