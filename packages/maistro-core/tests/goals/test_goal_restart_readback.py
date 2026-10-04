"""Restart read-back for the durable Goal composition (#1572).

The closure criterion this file exists for: restart a supported durable
composition and read back the same Goal, the same revision chain, and the
same bound Run provenance. The supported durable composition at the
maistro-core tier is the SQLite one — one aiosqlite database carrying the
Goal tables and the canonical Runs together, exactly what a single-process
deployment holds. Everything is written, every connection is closed, and
fresh stores are opened on the file before anything is asserted.
"""

from __future__ import annotations

import aiosqlite

from maistro.goals import GoalRevisionDraft, GoalStatus
from maistro.goals.sqlite_store import SqliteGoalStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import RunStatus
from maistro.runs.admission import admit_direct_work
from maistro.runs.sqlite_store import SqliteRunStore

KIND = "transform.format_markdown"
WORKSPACE = "ws-restart"


async def _project_tree() -> tuple[InMemoryProjectScopeStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    project = await projects.create(
        workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Durable"
    )
    return projects, project.project_id


async def test_goal_revisions_and_bound_run_provenance_survive_a_restart(
    tmp_path,
) -> None:
    db_path = tmp_path / "composition.db"

    # --- first process: write everything, then close the database --------
    projects, project_id = await _project_tree()
    goals_conn = await aiosqlite.connect(db_path)
    goals = SqliteGoalStore(goals_conn)
    await goals.ensure_schema()
    goal = await goals.create_goal(
        workspace_id=WORKSPACE,
        project_id=project_id,
        agent_id="agent-7",
        draft=GoalRevisionDraft(desired_state="first shape", author="op-1"),
    )
    goal = await goals.append_revision(
        goal.goal_id,
        GoalRevisionDraft(desired_state="second shape", author="op-1"),
        expected_revision=1,
    )
    goal = await goals.reassign_agent(goal.goal_id, "agent-8", expected_revision=2, actor="op-1")

    runs_conn = await aiosqlite.connect(db_path)
    runs = SqliteRunStore(runs_conn, project_store=projects)
    await runs.ensure_schema()
    run = await admit_direct_work(
        runs,
        workspace_id=WORKSPACE,
        project_id=project_id,
        node_type=KIND,
        name="work the goal",
        source="test",
        actor_principal_id="op-1",
        goal_id=goal.goal_id,
        goal_revision=2,
    )
    await runs.transition_run(run.run_id, RunStatus.QUEUED)
    await goals.transition_goal(
        goal.goal_id, GoalStatus.SATISFIED, expected_revision=2, actor="op-1"
    )
    await goals_conn.commit()
    await runs_conn.commit()
    await goals_conn.close()
    await runs_conn.close()

    # --- second process: fresh stores over the same file -----------------
    projects_after, _ = await _project_tree()
    goals_conn_after = await aiosqlite.connect(db_path)
    runs_conn_after = await aiosqlite.connect(db_path)
    try:
        goals_after = SqliteGoalStore(goals_conn_after)
        runs_after = SqliteRunStore(runs_conn_after, project_store=projects_after)

        read_goal = await goals_after.get_goal(goal.goal_id)
        assert read_goal.status is GoalStatus.SATISFIED
        assert read_goal.agent_id == "agent-8"
        assert read_goal.current_revision == 2

        chain = await goals_after.list_goal_revisions(goal.goal_id)
        assert [revision.revision for revision in chain] == [1, 2]
        assert [revision.desired_state for revision in chain] == ["first shape", "second shape"]
        assert [revision.author for revision in chain] == ["op-1", "op-1"]

        records = await goals_after.list_goal_transitions(goal.goal_id)
        assert [record.kind.value for record in records] == ["agent-reassign", "status"], (
            "both recorded mutations survived"
        )
        assert records[0].from_agent_id == "agent-7"
        assert records[0].to_agent_id == "agent-8"
        assert records[1].from_status is GoalStatus.ACTIVE
        assert records[1].to_status is GoalStatus.SATISFIED

        read_run = await runs_after.get_run(run.run_id)
        assert read_run is not None
        assert (read_run.goal_id, read_run.goal_revision) == (goal.goal_id, 2), (
            "the Run kept the revision it was admitted against, not the Goal's current one"
        )
    finally:
        await goals_conn_after.close()
        await runs_conn_after.close()
