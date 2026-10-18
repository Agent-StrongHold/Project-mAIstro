"""Workspace Goal inspection: a read-time projection over canonical sources (#65).

The product hierarchy (ADR-081226-9944, INTEROP-ONTOLOGY-v1 #458) puts the
Goal above execution: `Workspace -> Project -> Goal -> accountable Agent ->
Runs as evidence`. The canonical Goal store is `maistro.goals` (#1572). Goal-driven Runs bind
that Goal and its exact revision immutably at admission in `Run.goal_id` and
`Run.goal_revision`; historical Runs may carry an older provenance context.
This projection reads both through their scoped public seams, with immutable
Run bindings taking precedence over the legacy provenance representation.

This module is Conductor's inspection projection over that evidence, and it
deliberately has the same shape as `services.attention` (#1049): computed on
every read from the owners that already hold the state, persisted nowhere,
transitioning nothing. It is not a Goal store, not a reconciliation authority,
and not a second Run lifecycle (#65's stop condition): every run fact it
serves is read through `services.dag_run_inspection` — the #1036
list/detail/control seam — so the run identity, status, and control a Goal
view shows are exactly what that seam serves, with no translation.

What this projection refuses to do is decide Goal state. A completed or failed
Run is evidence; the view exposes an `execution_disposition` derived
deterministically from canonical Run statuses and reads `goal_state` only from
the scoped canonical Goal authority. A terminal Run can therefore never
silently render its Goal terminal.

Authorization is not re-decided here either. Runs enter only through
`list_visible_runs` (the caller's canonical Workspace universe, #1174), so a
Goal whose evidence the caller cannot see is — by protocol contract — a Goal
that does not exist for them.
"""

from __future__ import annotations

from typing import Any

from maistro.runs.goal_context import GoalContext, goal_context_of
from maistro.runs.model import Run, RunStatus
from services.dag_run_inspection import canonical_runs_for, list_visible_runs
from services.dag_run_store import MAX_RUNS

#: How many runs of evidence one page of goals may be built from. The window
#: the #1036 list door serves; grouping never widens it.
_EVIDENCE_WINDOW = MAX_RUNS

#: Deterministic execution dispositions, most-actionable first. Every value is
#: derived from canonical Run statuses only — `waiting_human` is the canonical
#: human pause (Run PAUSED, `reconciliation._parked_run_status` parks a Run
#: there for a human pause and nowhere else), `blocked` a failed/timed-out
#: Run, `active` a Run still admitted-and-unsettled, `waiting` the canonical
#: non-human parked state. There is no "stopping" value: the canonical Run
#: spine exposes no such intermediate, and this projection does not invent one
#: (#65: states are distinguishable *where the canonical owners expose them*).
#: None of them is a Goal verdict.
DISPOSITION_WAITING_HUMAN = "waiting_human"
DISPOSITION_BLOCKED = "blocked"
DISPOSITION_ACTIVE = "active"
DISPOSITION_WAITING = "waiting"
DISPOSITION_EVIDENCE_SETTLED = "evidence_settled"

_ACTIVE_RUN_STATUS_NAMES = frozenset(
    {RunStatus.CREATED.value, RunStatus.QUEUED.value, RunStatus.RUNNING.value}
)


def _disposition(statuses: list[str]) -> str:
    """One disposition for a goal's evidence, in the priority order above."""
    if "paused" in statuses:
        return DISPOSITION_WAITING_HUMAN
    if "failed" in statuses or "timed_out" in statuses:
        return DISPOSITION_BLOCKED
    if any(status in _ACTIVE_RUN_STATUS_NAMES for status in statuses):
        return DISPOSITION_ACTIVE
    if "waiting" in statuses:
        return DISPOSITION_WAITING
    return DISPOSITION_EVIDENCE_SETTLED


def _blocker(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The failed or timed-out Run a blocked disposition points at."""
    for row in rows:
        if row["status"] in ("failed", "timed_out"):
            return {
                "run_id": row["run_id"],
                "canonical_run_id": row["canonical_run_id"],
                "status": row["status"],
                "error": row["error"],
            }
    return None


def _context_for(run: Run | None) -> GoalContext | None:
    """The Goal identity bound to ``run``, with legacy provenance fallback.

    ``Run.goal_id``/``goal_revision`` are the canonical admission binding.
    Provenance is considered only for pre-binding records; letting it override
    a binding would create a second, mutable Goal association for a Run.
    """
    if run is None:
        return None
    if run.goal_id is not None and run.goal_revision is not None:
        return GoalContext(goal_id=run.goal_id, goal_revision=str(run.goal_revision))
    return goal_context_of(run.provenance)


async def _canonical_goal_facts(
    user_id: str, goal_ids: set[str]
) -> dict[str, tuple[Any, dict[int, Any]]]:
    """Visible canonical Goals and their revisions, keyed by Goal id.

    The product never opens the raw Goal store: ``goal_reader`` makes the same
    Workspace-scoped, non-disclosing decision as all other Goal consumers.
    A missing bridge, deleted historical Goal, or inaccessible Goal leaves the
    Run evidence readable without inventing current Goal state.
    """
    if not goal_ids:
        return {}
    try:
        from services.engine import get_engine

        reader = get_engine().goal_reader
        if reader is None:
            return {}
    except Exception:
        return {}

    facts: dict[str, tuple[Any, dict[int, Any]]] = {}
    for goal_id in goal_ids:
        try:
            goal = await reader.get_goal(goal_id, principal_id=user_id)
            revisions = await reader.list_goal_revisions(goal_id, principal_id=user_id)
        except LookupError:
            continue
        except Exception:
            # Goal inspection remains a read-only Run-evidence projection when
            # the independently owned Goal seam is temporarily unavailable.
            continue
        facts[goal_id] = (goal, {revision.revision: revision for revision in revisions})
    return facts


def _run_evidence_row(
    summary: dict[str, Any],
    context: GoalContext,
    run: Run | None,
) -> dict[str, Any]:
    """One Run of execution evidence, as the #1036 seam serves it.

    `run_id` is the id the #1036 detail/control routes answer on and
    `status` is the overlay-audited status that seam serves — copied, never
    translated. The canonical Run (when readable) contributes only facts the
    summary does not carry: lineage, actor, Graph identity, provenance.
    """
    row: dict[str, Any] = {
        "run_id": str(summary.get("id") or ""),
        "canonical_run_id": str(summary.get("canonical_run_id") or ""),
        "status": str(summary.get("status") or ""),
        "goal_revision": context.goal_revision,
        "dag_id": str(summary.get("dag_id") or ""),
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at"),
        "error": summary.get("error"),
        "parent_run_id": None,
        "parent_node_run_id": None,
        "actor_principal_id": None,
        "persona_id": None,
        "graph_id": None,
        "graph_name": None,
        "provenance": {},
    }
    if run is None:
        return row
    row.update(
        {
            "parent_run_id": run.parent_run_id,
            "parent_node_run_id": run.parent_node_run_id,
            "actor_principal_id": run.actor_principal_id,
            "persona_id": run.persona_id,
            "graph_id": run.graph.graph_id,
            "graph_name": run.graph.materialize().name,
            "provenance": run.provenance,
        }
    )
    return row


def _goal_view_for(
    goal_id: str,
    members: list[tuple[GoalContext, dict[str, Any], Run | None]],
    canonical_goal: Any | None = None,
    canonical_revisions: dict[int, Any] | None = None,
) -> dict[str, Any]:
    """One Goal's inspection view from its evidence rows.

    Goal-state fields come from the scoped canonical Goal reader when it can
    see the Goal — never defaults and never derived from outcomes. The Runs
    below are execution evidence and cannot flip that recorded state.
    """
    ordered = sorted(
        members,
        key=lambda m: (m[1].get("started_at") or 0, str(m[1].get("run_id") or "")),
        reverse=True,
    )
    rows = [_run_evidence_row(summary, context, run) for context, summary, run in ordered]
    contexts = [context for context, _summary, _run in ordered]

    def _recorded(pick) -> str | None:
        for context in contexts:
            value = pick(context)
            if value is not None:
                return value
        return None

    revisions = sorted(
        {context.goal_revision for context in contexts},
        key=lambda revision: (
            not revision.isdecimal(),
            int(revision) if revision.isdecimal() else revision,
        ),
    )
    canonical_revisions = canonical_revisions or {}
    # `ordered` is newest evidence first; a lexical sort would incorrectly
    # select revision "9" over revision "10" for its desired-state details.
    seen_revision = contexts[0].goal_revision if contexts else None
    exact_revision = (
        canonical_revisions.get(int(seen_revision))
        if seen_revision is not None and seen_revision.isdecimal()
        else None
    )
    graphs: dict[str, dict[str, Any]] = {}
    unmatched_pipelines: list[str] = []
    for row in rows:
        if row["graph_id"]:
            graphs.setdefault(
                str(row["graph_id"]), {"graph_id": row["graph_id"], "name": row["graph_name"]}
            )
        elif row["dag_id"] and row["dag_id"] not in unmatched_pipelines:
            # A projection row whose canonical Run is unreadable still shows
            # the pipeline that ran — under the projection's own identity, so
            # a legacy dag_id is never passed off as a canonical Graph id.
            unmatched_pipelines.append(row["dag_id"])
    statuses = [row["status"] for row in rows]
    summary_row = ordered[0][1]
    return {
        "goal_id": goal_id,
        "workspace_id": summary_row.get("workspace_id"),
        "project_id": summary_row.get("project_id"),
        "goal_state": canonical_goal.status if canonical_goal is not None else None,
        "goal_state_source": "canonical_goal" if canonical_goal is not None else "not_recorded",
        "goal_revision_seen": seen_revision,
        "goal_revisions": revisions,
        "accountable_agent_id": (
            canonical_goal.agent_id
            if canonical_goal is not None
            else _recorded(lambda c: c.accountable_agent_id)
        ),
        "desired_state": (
            exact_revision.desired_state
            if exact_revision is not None
            else _recorded(lambda c: c.desired_state)
        ),
        "success_condition": (
            exact_revision.success_conditions[0]
            if exact_revision is not None and exact_revision.success_conditions
            else _recorded(lambda c: c.success_condition)
        ),
        "stop_condition": (
            exact_revision.stop_conditions[0]
            if exact_revision is not None and exact_revision.stop_conditions
            else _recorded(lambda c: c.stop_condition)
        ),
        "success_conditions": (
            list(exact_revision.success_conditions) if exact_revision is not None else []
        ),
        "stop_conditions": list(exact_revision.stop_conditions)
        if exact_revision is not None
        else [],
        "parent_goal_id": (
            canonical_goal.parent_goal_id
            if canonical_goal is not None
            else _recorded(lambda c: c.parent_goal_id)
        ),
        "execution_disposition": _disposition(statuses),
        "blocker": _blocker(rows),
        "selected_graphs": list(graphs.values()),
        "unmatched_pipelines": unmatched_pipelines,
        "run_count": len(rows),
        "runs": rows,
    }


def _link_subgoals(views: list[dict[str, Any]]) -> None:
    """Fill `subgoals` from the sibling goals' recorded parentage.

    Subgoal lineage is Goal -> Goal (ontology `goal_subgoal`). Canonical Goal
    parentage is preferred when available; the link is drawn only between
    goals in the same Workspace and Project — a
    parent id from another scope is delegation beyond this view's boundary
    and stays invisible, like any other out-of-scope object (#1174).
    """
    by_scope: dict[tuple[str, str], dict[str, object]] = {}
    for view in views:
        key = (str(view.get("workspace_id") or ""), str(view.get("project_id") or ""))
        by_scope.setdefault(key, {})[str(view["goal_id"])] = view.get("parent_goal_id")
    for view in views:
        key = (str(view.get("workspace_id") or ""), str(view.get("project_id") or ""))
        me = str(view["goal_id"])
        recorded_parents = by_scope.get(key, {})
        view["subgoals"] = sorted(
            goal_id
            for goal_id, parent_of in recorded_parents.items()
            if parent_of == me and goal_id != me
        )


async def _collect_goal_views(user_id: str) -> list[dict[str, Any]]:
    """Every Goal view in the caller's Workspace universe, most recent first."""
    summaries = await list_visible_runs(user_id, limit=_EVIDENCE_WINDOW)
    if not summaries:
        return []
    # One batched canonical Run read for the page — the same door the status
    # overlay uses — so Run bindings never come from a product-private copy
    # (#65; #1174's one-door rule).
    canonical = await canonical_runs_for(
        user_id, [str(summary.get("canonical_run_id") or "") for summary in summaries]
    )
    grouped: dict[tuple[str, str, str], list[tuple[GoalContext, dict[str, Any], Run | None]]] = {}
    for summary in summaries:
        run = canonical.get(str(summary.get("canonical_run_id") or ""))
        context = _context_for(run)
        if context is None:
            # Not goal-driven evidence: the run stays exactly where it was —
            # on the #1036 run surfaces — and no pseudo-Goal is minted for it.
            continue
        key = (
            str(summary.get("workspace_id") or ""),
            str(summary.get("project_id") or ""),
            context.goal_id,
        )
        grouped.setdefault(key, []).append((context, summary, run))
    canonical_facts = await _canonical_goal_facts(user_id, {goal_id for (_, _, goal_id) in grouped})
    views = [
        _goal_view_for(goal_id, members, *canonical_facts.get(goal_id, (None, {})))
        for (_, _, goal_id), members in grouped.items()
    ]

    def _activity(view: dict[str, Any]) -> tuple[float, str]:
        runs = view["runs"]
        latest = max((row.get("started_at") or 0 for row in runs), default=0)
        return (float(latest), str(view["goal_id"]))

    views.sort(key=_activity, reverse=True)
    _link_subgoals(views)
    return views


async def list_goal_views(
    user_id: str, *, limit: int = 25, workspace_id: str | None = None
) -> list[dict[str, Any]]:
    """Goal inspection views, restricted to the caller's Workspace universe.

    `workspace_id` narrows the page to one Workspace the caller is a member
    of (the #65 inspection route's shape): the universe scoping underneath is
    unchanged — a Workspace the caller cannot see answers empty, never 403.
    """
    views = await _collect_goal_views(user_id)
    if workspace_id is not None:
        views = [view for view in views if view.get("workspace_id") == workspace_id]
    return views[: max(0, limit)]


async def goal_view(
    user_id: str, goal_id: str, *, workspace_id: str | None = None
) -> dict[str, Any] | None:
    """One Goal's inspection view, or None when the caller may not see one.

    None answers "does not exist" and "exists beyond your boundary"
    identically — the #1174 refusal shape. A goal_id is scoped to exactly one
    Project (ontology `project_goal`), so within one caller's universe an id
    names at most one view; evidence in a second scope is surfaced as
    `also_in` rather than silently merged into the wrong Project's history.
    With `workspace_id`, the primary history must be that Workspace's: the
    same goal_id recorded only elsewhere answers None (a 404-shaped refusal,
    not a silent cross-Workspace merge).
    """
    views = await _collect_goal_views(user_id)
    matches = [view for view in views if view["goal_id"] == goal_id]
    if workspace_id is not None:
        scoped = [view for view in matches if view.get("workspace_id") == workspace_id]
        matches = scoped + [view for view in matches if view not in scoped]
        if not scoped:
            return None
    if not matches:
        return None
    view = dict(matches[0])
    others = [
        {"workspace_id": v.get("workspace_id"), "project_id": v.get("project_id")}
        for v in matches[1:]
    ]
    view["also_in"] = others
    return view


def goal_state_is_recorded(view: dict[str, Any]) -> bool:
    """Whether a view carries a canonical Goal verdict.

    The verdict comes only from the scoped canonical Goal reader. Run outcomes
    remain execution evidence and cannot affect this answer.
    """
    return view.get("goal_state") is not None


__all__ = [
    "DISPOSITION_ACTIVE",
    "DISPOSITION_BLOCKED",
    "DISPOSITION_EVIDENCE_SETTLED",
    "DISPOSITION_WAITING",
    "DISPOSITION_WAITING_HUMAN",
    "goal_state_is_recorded",
    "goal_view",
    "list_goal_views",
]
