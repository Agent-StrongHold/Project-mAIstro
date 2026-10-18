"""Workspace Goal inspection is a read-time projection over canonical sources (#65).

`services.goal_inspection` must hold no Goal state of its own: every Goal
view is computed on read from the canonical Run evidence the #1036
inspection seam serves, grouped by the immutable Goal binding stamped at
canonical Run admission (`Run.goal_id` / `Run.goal_revision`, #1572). The
contract pinned here, one test per boundary:

- one Goal with many Runs is ONE history, never duplicated pseudo-tasks;
- run identity and status in a Goal view are exactly what
  `visible_run_detail` serves — no translation, no second terminal status;
- a terminal Run is evidence: Goal state comes only from the scoped canonical
  Goal reader, and the disposition names execution, not a Goal verdict;
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
_REVISION = 1

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


async def _bridge(monkeypatch: pytest.MonkeyPatch, store: Any, goal_store: Any) -> Any:
    """Point the engine at canonical Run and Goal readers, as production does."""
    import services.engine as engine_mod

    from maistro.goals.authorization import ScopedGoalStore
    from maistro.runs.scoped_reads import ScopedRunReader

    workspaces = _canonical_workspaces()
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    goal_reader = ScopedGoalStore(goal_store, workspaces)
    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_store=store, run_reader=reader, goal_reader=goal_reader),
    )
    return workspaces


class _Scene:
    """One test's canonical universe: a workspace, a bridged run store, and
    the projection rows seeded for its runs. Tests that need several Runs —
    or Runs in a foreign Workspace — add them here, never by re-bridging:
    the engine bridge is process-global, and a second bridge would orphan the
    first scene's canonical Runs (the seam then fail-closes the whole batch,
    as it must)."""

    def __init__(self, view: Any, workspaces: Any, store: Any, goal_store: Any) -> None:
        self.view = view
        self.workspaces = workspaces
        self.store = store
        self.goal_store = goal_store

    async def add_goal_run(
        self,
        *,
        goal_id: str,
        revision: int = _REVISION,
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
        from maistro.goals import GoalRevisionDraft
        from maistro.graph import Graph, Node
        from maistro.runs import RunStatus

        workspace = workspace_id or self.view.id
        root = await self.workspaces.project_store.root_for_workspace(workspace)
        graph = Graph(
            workspace_id=workspace,
            project_id=root.project_id,
            name=f"Goal work {goal_id}",
            nodes=[Node(node_id="n", node_type="agent")],
        )
        bind_goal = provenance is None
        if bind_goal:
            goal = await self.goal_store.get_goal(goal_id)
            if goal is None:
                parent_goal_id = (provenance_extra or {}).get("parent_goal_id")
                goal = await self.goal_store.create_goal(
                    workspace_id=workspace,
                    project_id=root.project_id,
                    agent_id="workspace-agent-1",
                    parent_goal_id=parent_goal_id,
                    goal_id=goal_id,
                    draft=GoalRevisionDraft(
                        desired_state="report shipped",
                        success_conditions=("report accepted by requester",),
                        stop_conditions=("requester withdraws the request",),
                        author=_USER_ID,
                    ),
                )
            while goal.current_revision < revision:
                goal = await self.goal_store.append_revision(
                    goal_id,
                    GoalRevisionDraft(
                        desired_state=f"report shipped revision {goal.current_revision + 1}",
                        success_conditions=("report accepted by requester",),
                        stop_conditions=("requester withdraws the request",),
                        author=_USER_ID,
                    ),
                    expected_revision=goal.current_revision,
                )
            provenance = dict(provenance_extra or {})
        run = await self.store.create_run(
            graph,
            provenance=provenance,
            parent_run_id=parent_run_id,
            parent_node_run_id=parent_node_run_id,
            # Canonical admission requires a named actor (store_boundary
            # `require_admitted_actor`); the same default every canonical
            # store test admits under.
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            **({"goal_id": goal_id, "goal_revision": revision} if bind_goal else {}),
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
    from maistro.goals import InMemoryGoalStore
    from maistro.runs import InMemoryRunStore

    view = await _owned_workspace()
    workspaces = _canonical_workspaces()
    store = InMemoryRunStore(project_store=workspaces.project_store)
    goal_store = InMemoryGoalStore()
    await _bridge(monkeypatch, store, goal_store)
    return _Scene(view, workspaces, store, goal_store)


async def _goal_scene(
    monkeypatch: pytest.MonkeyPatch,
    *,
    goal_id: str,
    statuses: list[Any],
    revision: int = _REVISION,
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
    assert view["goal_revisions"] == [str(_REVISION)]
    assert view["goal_revision_seen"] == str(_REVISION)
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


async def test_the_seam_relays_the_recorded_goal_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run seam relays the Goal identity a goal-driven Run records, and
    the round trip needs no translation: the ids on the run detail are the
    exact strings the Goal view groups that same run under. A run whose
    provenance names no Goal relays no goal_context at all — absence, not an
    invented default (#65; the Goal -> Run -> Goal navigation contract)."""
    from services.dag_run_inspection import visible_run_detail

    from maistro.runs import RunStatus
    from maistro.runs.goal_context import GOAL_ID_KEY, GOAL_REVISION_KEY

    goal_id = _next_id("goal")
    revision = 2
    scene, run_ids = await _goal_scene(
        monkeypatch, goal_id=goal_id, statuses=[RunStatus.COMPLETED], revision=revision
    )
    plain_projection_id = await scene.add_goal_run(
        goal_id=_next_id("unamed"),
        status=RunStatus.COMPLETED,
        provenance={"unrelated": "projection-only row"},
    )

    detail = await visible_run_detail(_USER_ID, run_ids[0])
    assert detail is not None
    assert detail["goal_context"] == {"goal_id": goal_id, "goal_revision": str(revision)}

    plain = await visible_run_detail(_USER_ID, plain_projection_id)
    assert plain is not None
    assert "goal_context" not in plain

    # And the same two strings the Goal view groups this run by — read here
    # through the goal provenance the view itself consumes — so linking back
    # from the run surface lands on exactly this Goal's history.
    view = (await _views_for(goal_id))[0]
    row = next(row for row in view["runs"] if row["run_id"] == run_ids[0])
    assert row["goal_revision"] == detail["goal_context"]["goal_revision"]
    assert view["goal_id"] == detail["goal_context"][GOAL_ID_KEY]
    assert detail["goal_context"][GOAL_REVISION_KEY] == str(revision)


# ─── evidence is not a verdict ───────────────────────────────────────────────


async def test_completed_runs_do_not_render_the_goal_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed Run is evidence; only canonical Goal state may say 'done'."""
    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    await _goal_scene(monkeypatch, goal_id=goal_id, statuses=[RunStatus.COMPLETED])

    view = (await _views_for(goal_id))[0]
    assert view["goal_state"] == "active"
    assert view["goal_state_source"] == "canonical_goal"
    assert view["execution_disposition"] == "evidence_settled", (
        "the disposition names execution evidence, never a Goal verdict"
    )


async def test_canonical_goal_state_and_bound_revision_are_not_derived_from_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Goal reader supplies state and the Run's immutable revision selects
    its desired state, even after the Goal moves on or reaches another terminal
    state. This is the production admission representation, not legacy
    provenance fabricated by the projection test."""
    from maistro.goals import GoalRevisionDraft, GoalStatus
    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    scene, _run_ids = await _goal_scene(
        monkeypatch, goal_id=goal_id, statuses=[RunStatus.COMPLETED]
    )
    moved = await scene.goal_store.append_revision(
        goal_id,
        GoalRevisionDraft(
            desired_state="new direction",
            success_conditions=("new proof",),
            stop_conditions=("new stop",),
            author=_USER_ID,
        ),
        expected_revision=1,
    )
    await scene.goal_store.transition_goal(
        goal_id,
        GoalStatus.CANCELLED,
        expected_revision=moved.current_revision,
        actor=_USER_ID,
    )

    view = (await _views_for(goal_id))[0]
    assert view["goal_state"] == GoalStatus.CANCELLED
    assert view["goal_state_source"] == "canonical_goal"
    assert view["goal_revision_seen"] == "1"
    assert view["desired_state"] == "report shipped"
    assert view["success_conditions"] == ["report accepted by requester"]
    assert view["stop_conditions"] == ["requester withdraws the request"]
    assert view["execution_disposition"] == "evidence_settled"


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
    # The failure is execution evidence; it cannot turn the active Goal failed.
    assert view["goal_state"] == "active"


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


async def test_hitl_pause_provenance_stays_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run parked at the HITL fence stays visible in its Goal's history as
    waiting-human, with the admission's own record of the pause riding
    through verbatim and its identity exactly what the run seam answers —
    the pause is execution evidence the reader can trace, never something a
    Goal-side projection reclassifies or drops (#65: HITL provenance is
    visible)."""
    from services.dag_run_inspection import visible_run_detail

    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    scene = await _make_scene(monkeypatch)
    projection_id = await scene.add_goal_run(
        goal_id=goal_id,
        status=RunStatus.PAUSED,
        provenance_extra={
            "pause": {"waiting_on": "human_review", "requested_by": "reviewer-7"},
        },
    )

    view = (await _views_for(goal_id))[0]
    assert view["execution_disposition"] == "waiting_human"
    row = next(row for row in view["runs"] if row["run_id"] == projection_id)
    assert row["status"] == "paused"
    # The recorded context of the pause rides through untouched: same keys,
    # same values, nothing summarized away.
    assert row["provenance"]["pause"] == {
        "waiting_on": "human_review",
        "requested_by": "reviewer-7",
    }
    # Goal identity is the immutable Run binding, not a mutable provenance key.
    assert row["goal_revision"] == str(_REVISION)
    # And the row is the seam's own answer for that run, so tracing the pause
    # to its execution (detail, attempts, events) is the same door everyone
    # else uses — no Goal-side copy of the run.
    through_the_seam = await visible_run_detail(_USER_ID, projection_id)
    assert through_the_seam is not None
    assert row["run_id"] == through_the_seam["id"]
    assert row["status"] == through_the_seam["status"]
    assert through_the_seam["goal_context"] == {
        "goal_id": goal_id,
        "goal_revision": str(_REVISION),
    }


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


async def test_retry_of_a_failed_attempt_stays_in_one_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry/replan is a new Run whose lineage names the attempt it
    supersedes. The view keeps both attempts in the Goal's ONE history, the
    retry's admission provenance rides through verbatim (the admission path's
    own spelling of why the run exists — arbitrary to this view), and the
    failed attempt stays failed — no Goal-side notion of attempts may erase
    or reclassify either row."""
    from maistro.runs import RunStatus

    goal_id = _next_id("goal")
    scene = await _make_scene(monkeypatch)
    failed_projection_id = await scene.add_goal_run(goal_id=goal_id, status=RunStatus.FAILED)
    failed_canonical = _canonical_of(scene, failed_projection_id)
    retry_projection_id = await scene.add_goal_run(
        goal_id=goal_id,
        status=RunStatus.RUNNING,
        parent_run_id=failed_canonical,
        provenance_extra={"retry_of": failed_canonical},
    )

    view = (await _views_for(goal_id))[0]
    assert view["run_count"] == 2, "a retry is the same Goal's history, not a second one"
    rows = {row["run_id"]: row for row in view["runs"]}
    retry = rows[retry_projection_id]
    assert retry["parent_run_id"] == failed_canonical
    assert retry["provenance"]["retry_of"] == failed_canonical
    assert retry["status"] == "running"
    # The superseded attempt's evidence is untouched: still failed, still the
    # blocker — a retry explains the failure, it does not retcon it.
    assert rows[failed_projection_id]["status"] == "failed"
    assert view["blocker"] is not None
    assert view["blocker"]["run_id"] == failed_projection_id


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


async def _member_route_scene(
    monkeypatch: pytest.MonkeyPatch, *, member_id: str = "user", role: str = "editor"
) -> Any:
    """A bridged scene whose Workspace the authed_client principal can see.

    The scene is owned by `_USER_ID`; `member_id` (the login the route
    tests authenticate as) is added as a member so the #1174 universe the
    routes read is non-empty for them.
    """
    from services.workspace_authority import set_member

    scene = await _make_scene(monkeypatch)
    await set_member(scene.view.id, user_id=member_id, role=role)  # type: ignore[arg-type]
    return scene


async def test_goals_routes_are_scoped_and_read_only(
    monkeypatch: pytest.MonkeyPatch, authed_client: Any
) -> None:
    """GET /v1/workspaces/{id}/goals answers a member's Workspace; nothing
    else exists."""
    from maistro.runs import RunStatus

    scene = await _member_route_scene(monkeypatch)
    goal_id = _next_id("goal")
    await scene.add_goal_run(goal_id=goal_id, status=RunStatus.RUNNING)

    listed = authed_client.get(f"/v1/workspaces/{scene.view.id}/goals")
    assert listed.status_code == 200
    assert isinstance(listed.json(), list)
    assert [row["goal_id"] for row in listed.json()] == [goal_id]
    missing = authed_client.get(f"/v1/workspaces/{scene.view.id}/goals/never-a-goal")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "goal not found"
    # Read-only surface: no mutating verb is offered on the router.
    refused = authed_client.post(f"/v1/workspaces/{scene.view.id}/goals", json={})
    assert refused.status_code >= 400


async def test_goal_route_prefix_lives_under_the_declared_workspaces_mount(
    authed_client: Any,
) -> None:
    """The inspection door is /v1/workspaces/{id}/goals — the mount the
    route-permission registry already declares (#1048/#1049 shape).

    A reintroduced top-level /v1/goals prefix would be a brand-new
    authenticated surface the registry has reviewed no exemption for; the
    CI route-permission gate fails exactly that shape, so this pins it at
    the HTTP level too.
    """
    legacy = authed_client.get("/v1/goals")
    assert legacy.status_code == 404
    unmounted = authed_client.get("/v1/goals/some-goal")
    assert unmounted.status_code == 404


async def test_goal_routes_refuse_non_members_without_an_existence_oracle(
    authed_client: Any,
) -> None:
    """Not a member and not a Workspace are the same 404 (#1174 shape)."""
    foreign = await _owned_workspace()  # owned by _USER_ID, not the login
    for path in (
        f"/v1/workspaces/{foreign.id}/goals",
        f"/v1/workspaces/{foreign.id}/goals/some-goal",
        "/v1/workspaces/never-a-workspace/goals",
    ):
        refused = authed_client.get(path)
        assert refused.status_code == 404
        assert refused.json()["detail"] == "workspace not found"


async def test_goal_routes_stay_in_the_requested_workspace(
    monkeypatch: pytest.MonkeyPatch, authed_client: Any
) -> None:
    """A Goal recorded in one Workspace does not answer under another, even
    for a member of both — no silent cross-Workspace history merge."""
    from services.workspace_authority import create_workspace

    from maistro.runs import RunStatus

    scene = await _member_route_scene(monkeypatch)
    other = await create_workspace(
        creator_user_id="user",
        name=f"Goal Inspection other {next(_seq)}",
        persona_template_id="pm_fleet",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    goal_id = _next_id("goal")
    await scene.add_goal_run(goal_id=goal_id, status=RunStatus.RUNNING)

    in_scope = authed_client.get(f"/v1/workspaces/{scene.view.id}/goals")
    assert in_scope.status_code == 200
    assert [row["goal_id"] for row in in_scope.json()] == [goal_id]
    under_other = authed_client.get(f"/v1/workspaces/{other.id}/goals")
    assert under_other.status_code == 200
    assert under_other.json() == []
    misplaced = authed_client.get(f"/v1/workspaces/{other.id}/goals/{goal_id}")
    assert misplaced.status_code == 404
    assert misplaced.json()["detail"] == "goal not found"


async def test_viewer_members_can_read_goal_inspection(
    monkeypatch: pytest.MonkeyPatch, authed_client: Any
) -> None:
    """Inspection is a member read, like Home: a viewer may look, and the
    route offers nothing to write."""
    from maistro.runs import RunStatus

    scene = await _member_route_scene(monkeypatch, role="viewer")
    goal_id = _next_id("goal")
    await scene.add_goal_run(goal_id=goal_id, status=RunStatus.RUNNING)

    listed = authed_client.get(f"/v1/workspaces/{scene.view.id}/goals")
    assert listed.status_code == 200
    assert [row["goal_id"] for row in listed.json()] == [goal_id]
