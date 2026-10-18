"""Workspace Goal inspection is a read-time projection over canonical sources (#65).

`services.goal_inspection` must hold no Goal state of its own: every Goal
view is computed on read from the canonical Run evidence the #1036
inspection seam serves, grouped by the Goal context stamped in canonical
`Run.provenance` (`maistro.runs.goal_context`, #458). The contract pinned
here, one test per boundary:

- one Goal with many Runs is ONE history, never duplicated pseudo-tasks;
- run identity and status in a Goal view are exactly what
  `visible_run_detail` serves — no translation, no second terminal status;
- a terminal Run is evidence: `goal_state` stays `not_recorded` whatever the
  runs did, and the disposition names execution, not a Goal verdict;
- canonical pause/failure/terminal states stay distinguishable;
- provenance naming a Goal without its exact revision projects nothing
  (ontology: a projection may not invent `goal_revision`);
- a foreign Workspace's Goals are invisible, 404-shaped, both by list and by
  id (#1174);
- subgoal, child-run, and delegation lineage survives into the view.

Driven against the real canonical Workspace authority, a real
`InMemoryRunStore`, and the scoped reader the routes use — the
fabricated-Request style of test_dag_run_cancel_route.py — not mocks.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) in sys.path:
    sys.path.remove(str(_BACKEND))
sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("boundary")]

_USER_ID = "goal-inspection-user"
_REVISION = "r1"

_seq = iter(range(10_000))


def _next_id(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


async def _owned_workspace() -> Any:
    from services.workspace_authority import create_workspace

    return await create_workspace(
        creator_user_id=_USER_ID,
        name=f"Goal Inspection {next(_seq)}",
        persona_template_id="pm_fleet",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )


def _canonical_workspaces() -> Any:
    from services.workspace_authority import canonical_store_for_tests

    return canonical_store_for_tests()


async def _bridge(monkeypatch: pytest.MonkeyPatch, store: Any) -> Any:
    """Point the engine's canonical bridge at `store` through the scoped reader."""
    import services.engine as engine_mod

    from maistro.runs.scoped_reads import ScopedRunReader

    workspaces = _canonical_workspaces()
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    return workspaces


class _Scene:
    """One test's canonical universe: a workspace, a bridged run store, and
    the projection rows seeded for its runs. Tests that need several Runs —
    or Runs in a foreign Workspace — add them here, never by re-bridging:
    the engine bridge is process-global, and a second bridge would orphan the
    first scene's canonical Runs (the seam then fail-closes the whole batch,
    as it must)."""

    def __init__(self, view: Any, workspaces: Any, store: Any) -> None:
        self.view = view
        self.workspaces = workspaces
        self.store = store

    async def add_goal_run(
        self,
        *,
        goal_id: str,
        revision: str = _REVISION,
        status: Any = None,
        provenance_extra: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        parent_node_run_id: str | None = None,
        workspace_id: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> str:
        """One canonical Run admitted for real, plus its #1036 projection row.

        Returns the projection run id — the id the /v1/dag-runs routes answer
        on. With `workspace_id` the Run is admitted into *that* workspace
        instead (the foreign-visibility case). With `provenance` the default
        Goal context is replaced entirely (the revisionless/plain cases).
        """
        from maistro.graph import Graph, Node
        from maistro.runs import RunStatus
        from maistro.runs.goal_context import (
            ACCOUNTABLE_AGENT_ID_KEY,
            DESIRED_STATE_KEY,
            GOAL_ID_KEY,
            GOAL_REVISION_KEY,
            STOP_CONDITION_KEY,
            SUCCESS_CONDITION_KEY,
        )

        workspace = workspace_id or self.view.id
        root = await self.workspaces.project_store.root_for_workspace(workspace)
        graph = Graph(
            workspace_id=workspace,
            project_id=root.project_id,
            name=f"Goal work {goal_id}",
            nodes=[Node(node_id="n", node_type="agent")],
        )
        if provenance is None:
            provenance = {
                GOAL_ID_KEY: goal_id,
                GOAL_REVISION_KEY: revision,
                ACCOUNTABLE_AGENT_ID_KEY: "workspace-agent-1",
                DESIRED_STATE_KEY: "report shipped",
                SUCCESS_CONDITION_KEY: "report accepted by requester",
                STOP_CONDITION_KEY: "requester withdraws the request",
            }
            if provenance_extra:
                provenance.update(provenance_extra)
        run = await self.store.create_run(
            graph,
            provenance=provenance,
            parent_run_id=parent_run_id,
            parent_node_run_id=parent_node_run_id,
            # Canonical admission requires a named actor (store_boundary
            # `require_admitted_actor`); the same default every canonical
            # store test admits under.
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        # Walk the canonical lifecycle to the requested state without
        # revisiting one (RUNNING -> RUNNING is an illegal transition, by
        # design).
        if status is RunStatus.CREATED:
            steps: tuple[RunStatus, ...] = ()
        elif status is RunStatus.QUEUED:
            steps = (RunStatus.QUEUED,)
        elif status is None or status is RunStatus.RUNNING:
            steps = (RunStatus.QUEUED, RunStatus.RUNNING)
        else:
            steps = (RunStatus.QUEUED, RunStatus.RUNNING, status)
        for step in steps:
            await self.store.transition_run(run.run_id, step)
        return await self.seed_projection(run.run_id, workspace)

    async def seed_projection(self, canonical_run_id: str, workspace_id: str) -> str:
        """The projection row the #1036 write path records for a canonical Run."""
        from services.dag_run_store import get_dag_run_store

        run_id = _next_id("dag-goal")
        await get_dag_run_store().start_run(
            run_id=run_id,
            user_id=_USER_ID,
            workspace_id=workspace_id,
            canonical_run_id=canonical_run_id,
        )
        return run_id


async def _make_scene(monkeypatch: pytest.MonkeyPatch) -> _Scene:
    from maistro.runs import InMemoryRunStore

    view = await _owned_workspace()
    workspaces = _canonical_workspaces()
    store = InMemoryRunStore(project_store=workspaces.project_store)
    await _bridge(monkeypatch, store)
    return _Scene(view, workspaces, store)


async def _goal_scene(
    monkeypatch: pytest.MonkeyPatch,
    *,
    goal_id: str,
    statuses: list[Any],
    revision: str = _REVISION,
    extra: dict[str, Any] | None = None,
    parent_run_id: str | None = None,
    parent_node_run_id: str | None = None,
    workspace_id: str | None = None,
) -> tuple[_Scene, list[str]]:
    """A bridged scene plus N goal-driven runs seeded into it."""
    scene = await _make_scene(monkeypatch)
    run_ids = []
    for index, status in enumerate(statuses):
        run_ids.append(
            await scene.add_goal_run(
                goal_id=goal_id,
                revision=revision,
                status=status,
                provenance_extra=({**extra, "attempt": index} if extra else None),
                parent_run_id=parent_run_id,
                parent_node_run_id=parent_node_run_id,
                workspace_id=workspace_id,
            )
        )
    return scene, run_ids


async def _views_for(goal_id: str) -> list[dict[str, Any]]:
    from services.goal_inspection import list_goal_views

    views = await list_goal_views(_USER_ID, limit=100)
    return [view for view in views if view["goal_id"] == goal_id]


# ─── one Goal, many Runs: one history ────────────────────────────────────────


async def test_sequential_runs_form_one_goal_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sequential Runs under one Goal revision are one Goal, not two tasks."""
    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    _scene, run_ids = await _goal_scene(
        monkeypatch, goal_id=goal_id, statuses=[RunStatus.COMPLETED, RunStatus.RUNNING]
    )

    views = await _views_for(goal_id)
    assert len(views) == 1, "one Goal with several Runs must be one history"
    view = views[0]
    assert view["run_count"] == 2
    assert {row["run_id"] for row in view["runs"]} == set(run_ids)
    assert view["goal_revisions"] == [_REVISION]
    assert view["goal_revision_seen"] == _REVISION
    # Newest evidence first, so the history reads in execution order.
    assert [row["run_id"] for row in view["runs"]] == list(reversed(run_ids))


async def test_run_identity_and_status_are_the_run_seams_truth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No translation: every run row answers as /v1/dag-runs/{id} answers."""
    from services.dag_run_inspection import visible_run_detail

    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    _scene, _run_ids = await _goal_scene(
        monkeypatch, goal_id=goal_id, statuses=[RunStatus.CANCELLED, RunStatus.RUNNING]
    )

    view = (await _views_for(goal_id))[0]
    for row in view["runs"]:
        through_the_seam = await visible_run_detail(_USER_ID, row["run_id"])
        assert through_the_seam is not None
        assert row["run_id"] == through_the_seam["id"]
        assert row["status"] == through_the_seam["status"]
        assert row["canonical_run_id"] == through_the_seam["canonical_run_id"]
    assert {row["status"] for row in view["runs"]} == {"cancelled", "running"}


# ─── evidence is not a verdict ───────────────────────────────────────────────


async def test_completed_runs_do_not_render_the_goal_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed Run is evidence; only canonical Goal state may say 'done'."""
    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    await _goal_scene(monkeypatch, goal_id=goal_id, statuses=[RunStatus.COMPLETED])

    view = (await _views_for(goal_id))[0]
    assert view["goal_state"] is None
    assert view["goal_state_source"] == "not_recorded"
    assert view["execution_disposition"] == "evidence_settled", (
        "the disposition names execution evidence, never a Goal verdict"
    )


async def test_failed_run_surfaces_a_blocker_without_a_goal_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    _scene, _run_ids = await _goal_scene(
        monkeypatch, goal_id=goal_id, statuses=[RunStatus.FAILED, RunStatus.RUNNING]
    )

    view = (await _views_for(goal_id))[0]
    assert view["execution_disposition"] == "blocked"
    blocker = view["blocker"]
    assert blocker is not None and blocker["status"] == "failed"
    assert blocker["run_id"] in {row["run_id"] for row in view["runs"]}
    # The failure is execution evidence; the Goal itself has recorded nothing.
    assert view["goal_state"] is None


async def test_waiting_human_pause_is_distinguishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canonical human pause (PAUSED) reads as waiting-human; the canonical
    non-human parked state (WAITING) stays its own value."""
    from maistro.runs import RunStatus

    scene = await _make_scene(monkeypatch)
    human_goal = _next_id("goal")
    await scene.add_goal_run(goal_id=human_goal, status=RunStatus.PAUSED)
    parked_goal = _next_id("goal")
    await scene.add_goal_run(goal_id=parked_goal, status=RunStatus.WAITING)

    human = (await _views_for(human_goal))[0]
    parked = (await _views_for(parked_goal))[0]
    assert human["execution_disposition"] == "waiting_human"
    assert parked["execution_disposition"] == "waiting"
    assert human["execution_disposition"] != parked["execution_disposition"]


# ─── fail-closed Goal context ────────────────────────────────────────────────


async def test_a_goal_without_its_revision_projects_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provenance naming a goal_id without `goal_revision` is not evidence a
    projection may claim: inventing a revision would let a later Goal revision
    rewrite which history owns the run (#458)."""
    from maistro.runs import RunStatus
    from maistro.runs.goal_context import GOAL_ID_KEY

    orphan_goal = _next_id("goal")
    scene = await _make_scene(monkeypatch)
    await scene.add_goal_run(
        goal_id=orphan_goal, status=RunStatus.COMPLETED, provenance={GOAL_ID_KEY: orphan_goal}
    )

    assert await _views_for(orphan_goal) == [], (
        "a Goal context without its exact revision projects nothing"
    )


async def test_runs_without_goal_context_mint_no_pseudo_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary runs stay on the run surfaces; the Goal list does not invent
    Goals from them."""
    from maistro.runs import RunStatus

    scene = await _make_scene(monkeypatch)
    run_id = await scene.add_goal_run(
        goal_id=_next_id("unamed"), status=RunStatus.COMPLETED, provenance={}
    )

    from services.goal_inspection import list_goal_views

    views = await list_goal_views(_USER_ID, limit=100)
    assert all(row["run_id"] != run_id for view in views for row in view["runs"])


# ─── visibility ──────────────────────────────────────────────────────────────


async def test_foreign_workspace_goal_is_invisible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another principal's Goal is indistinguishable from one that does not
    exist — by list and by id (#1174): the projection row carries the foreign
    Workspace scope and the canonical Run is unreadable to this caller."""
    from services.goal_inspection import goal_view

    from maistro.runs import RunStatus

    scene = await _make_scene(monkeypatch)
    theirs = await _canonical_workspaces().create(
        creator_user_id="someone-else", name=f"Foreign {next(_seq)}"
    )
    foreign_goal = _next_id("goal")
    await scene.add_goal_run(
        goal_id=foreign_goal, status=RunStatus.RUNNING, workspace_id=theirs.workspace_id
    )

    assert await _views_for(foreign_goal) == []
    assert await goal_view(_USER_ID, foreign_goal) is None

    own_goal = _next_id("goal")
    await scene.add_goal_run(goal_id=own_goal, status=RunStatus.RUNNING)
    own = await goal_view(_USER_ID, own_goal)
    assert own is not None and own["goal_id"] == own_goal


async def test_goal_view_answers_by_id_without_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.goal_inspection import goal_view

    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    await _goal_scene(monkeypatch, goal_id=goal_id, statuses=[RunStatus.RUNNING])

    view = await goal_view(_USER_ID, goal_id)
    assert view is not None
    assert view["goal_id"] == goal_id
    assert view["also_in"] == []


# ─── lineage and strategy ────────────────────────────────────────────────────


async def test_subgoal_lineage_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delegated Subgoal links back to its parent Goal — one lineage, both
    directions, inside one Workspace/Project scope."""
    from maistro.runs import RunStatus
    from maistro.runs.goal_context import PARENT_GOAL_ID_KEY

    scene = await _make_scene(monkeypatch)
    parent_goal = _next_id("goal")
    child_goal = _next_id("goal")
    await scene.add_goal_run(goal_id=parent_goal, status=RunStatus.RUNNING)
    await scene.add_goal_run(
        goal_id=child_goal,
        status=RunStatus.RUNNING,
        provenance_extra={PARENT_GOAL_ID_KEY: parent_goal},
    )

    parent = (await _views_for(parent_goal))[0]
    child = (await _views_for(child_goal))[0]
    assert parent["subgoals"] == [child_goal]
    assert child["parent_goal_id"] == parent_goal


async def test_child_run_and_delegation_provenance_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child Run's parent lineage and the accountable-agent/delegation
    context ride through to the view unchanged."""
    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    scene = await _make_scene(monkeypatch)
    parent_projection_id = await scene.add_goal_run(goal_id=goal_id, status=RunStatus.RUNNING)
    parent_canonical = _canonical_of(scene, parent_projection_id)
    # A real parent NodeRun: the store validates a child Run's lineage, so
    # delegation provenance must point at execution that exists.
    parent_node_run = await scene.store.create_node_run(parent_canonical, node_id="n")
    child_projection_id = await scene.add_goal_run(
        goal_id=goal_id,
        status=RunStatus.RUNNING,
        parent_run_id=parent_canonical,
        parent_node_run_id=parent_node_run.node_run_id,
    )

    view = (await _views_for(goal_id))[0]
    assert view["run_count"] == 2
    child_rows = [row for row in view["runs"] if row["run_id"] == child_projection_id]
    assert child_rows and child_rows[0]["parent_run_id"] == parent_canonical
    assert child_rows[0]["parent_node_run_id"] == parent_node_run.node_run_id
    assert view["accountable_agent_id"] == "workspace-agent-1"
    assert view["desired_state"] == "report shipped"
    assert view["success_condition"] == "report accepted by requester"
    assert view["stop_condition"] == "requester withdraws the request"


def _canonical_of(scene: _Scene, projection_run_id: str) -> str:
    """The canonical run id a projection row carries (test-side lookup)."""
    from services.dag_run_store import get_dag_run_store

    row = get_dag_run_store().get_run(projection_run_id)
    assert row is not None
    return str(row["canonical_run_id"])


async def test_selected_graphs_come_from_canonical_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Graphs a Goal's evidence selected are canonical Graph ids — never
    the projection's dag_id passed off as one."""
    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    await _goal_scene(
        monkeypatch,
        goal_id=goal_id,
        statuses=[RunStatus.COMPLETED, RunStatus.RUNNING],
    )

    view = (await _views_for(goal_id))[0]
    assert view["selected_graphs"], "canonical Graph selection is recorded per run"
    graph_ids = {entry["graph_id"] for entry in view["selected_graphs"]}
    assert all(row["graph_id"] in graph_ids for row in view["runs"])


# ─── read-time, stateless ────────────────────────────────────────────────────


async def test_projection_persists_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading Goal views writes nothing: two reads agree, and the projection
    storage gains no records — the view survives restart/reconnect because
    every fact it serves already survives in its canonical owner."""
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    await _goal_scene(monkeypatch, goal_id=goal_id, statuses=[RunStatus.RUNNING])

    store = get_dag_run_store()
    before = {run["id"] for run in store.list_runs(limit=10_000)}
    first = await _views_for(goal_id)
    second = await _views_for(goal_id)
    after = {run["id"] for run in store.list_runs(limit=10_000)}

    assert first == second
    assert before == after, "a read-time projection must not write"


# ─── HTTP door ───────────────────────────────────────────────────────────────


def test_goals_routes_are_scoped_and_read_only(authed_client: Any) -> None:
    """GET /v1/goals answers the principal's universe; nothing else exists."""
    listed = authed_client.get("/v1/goals")
    assert listed.status_code == 200
    assert isinstance(listed.json(), list)
    missing = authed_client.get("/v1/goals/never-a-goal")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "goal not found"
    # Read-only surface: no mutating verb is offered on the router.
    refused = authed_client.post("/v1/goals", json={})
    assert refused.status_code >= 400
