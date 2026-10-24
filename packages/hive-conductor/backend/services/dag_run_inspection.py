"""Scoped inspection over the DAG-Run projection — the one authorization door (#1174).

`DagRunStore` is projection storage (#697): it answers what a run recorded to
whoever holds the id. That is an implementation detail, not an authorization
decision. Every reader of run data — the list/detail/SSE API routes and the
in-repo consumers that inspect runs (eval-judge scoring and its verdict
read side today; #804/#1046 extend the same door to Workspace/Home/Attention
surfaces) — goes through this module, which enforces the same canonical
boundary every other scoped Hive surface uses: the caller's Workspace
universe from `services.workspace_authority` (#37). Hive's legacy Workspace records are
never consulted here; the authority is the canonical store and nothing else.

A run is visible only inside the Workspace the canonical Run was admitted
into (mirrored onto the projection by the write path). A projection row that
carries no Workspace scope is a row written before #1174 threaded scope
through `start_run`: it is visible to no one, fail-closed, until #1036's
canonical inspection migration retires or re-scopes it.

`run.user_id` is deliberately NOT an authorization shortcut here. The
canonical boundary is Workspace membership; a route-local
`user_id == ...` comparison would be a second, divergent authority (#1174's
stop condition).

## Terminal status reconciles against the canonical Run (#35)

`DagRunStore` is a receipt of what the canonical execution reported, not an
authority: a projection row's free-text `status` is display state, and the
spine — Run/NodeRun/Attempt — owns whether work queued, ran, waited,
completed, failed, was cancelled or timed out. So every lifecycle fact this
door serves is reconciled against the canonical durable Run store when the
row carries the correlation to ask for one (`canonical_run_id`): if the
canonical Run resolves, its lifecycle replaces the row's — status AND finish
time, including null — so a stale, mis-written, or hand-planted row can
neither terminalize work the spine has not finished nor resurrect work the
spine has already finished, and cannot keep a locally stamped finish over a
Run the spine holds open (#1036). The served finish time is the canonical
Run's own `finished_at` in the epoch-seconds wire shape the projection
already speaks — never the projection's write clock and never a substitute
timestamp. In list, detail, and every consumer behind this door, across
restart, restore, replica handoff and cache reload, because the check runs
on every read.

The boundary is deliberate, and documented rather than blurred:

- a row with no `canonical_run_id` (written before correlation existed) is
  served as recorded — there is no canonical truth for it to contradict;
- a row whose canonical Run no longer resolves (an in-memory spine after a
  restart, say) is served as recorded — the row is the surviving receipt, and
  its recorded status was itself copied from canonical facts at write time;
- reconciliation never rewrites the stored record: provenance is preserved
  and only the served view carries the canonical status.

Nothing on the execution side reads this projection: admission, scheduling
and recovery operate on the canonical spine, so a projection row cannot
drive execution, recovery or admission decisions.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from services.dag_run_store import get_dag_run_store
from services.workspace_authority import list_views_for_user

logger = logging.getLogger("hive.dag_run_inspection")


async def authorized_workspace_ids(user_id: str) -> set[str]:
    """The canonical Workspaces whose runs `user_id` may inspect.

    One universe, computed once per request and shared by the list and the
    by-id lookups, so the two can never disagree about what is visible
    (#1174).
    """
    views = await list_views_for_user(user_id)
    return {view.id for view in views}


def _in_scope(record: dict[str, Any], allowed: set[str]) -> bool:
    # An empty scope is never in scope: a record that names no Workspace
    # proves nothing about where it executed, and guessing a visibility rule
    # for it would rebuild the leak this closes.
    return str(record.get("workspace_id") or "") in allowed


async def _canonical_run_lifecycle(canonical_run_id: str) -> dict[str, Any] | None:
    """The canonical Run's lifecycle facts, when this deployment can resolve them.

    `None` means "no canonical truth to reconcile against": an uncorrelated
    row, a Run this spine no longer holds, or a store that cannot be read.
    None of those turn the projection into an authority — the row is then a
    receipt whose lifecycle was copied from canonical facts when it was
    written. The finish time is the canonical Run's own `finished_at`
    (datetime -> epoch seconds, the projection's existing wire shape), so a
    served finish is derived from the spine's record rather than the
    projection's write clock (#1036).
    """
    if not canonical_run_id:
        return None
    try:
        # Lazy, like every cross-service import in this app: `dag_agents`
        # pulls the graph spine, and the import must not run at module load.
        from services.dag_agents import get_run_store

        record = await get_run_store().get(canonical_run_id)
    except Exception:
        logger.warning(
            "canonical_run_status_unavailable run_id=%s", canonical_run_id, exc_info=True
        )
        return None
    if record is None:
        return None
    run = getattr(record, "run", None)
    status = getattr(run, "status", None)
    if status is None:
        return None
    finished_at = getattr(run, "finished_at", None)
    if isinstance(finished_at, datetime):
        finished_at = finished_at.timestamp()
    return {
        "status": str(getattr(status, "value", status)),
        "finished_at": finished_at,
        "result": getattr(run, "result", None),
        "error": getattr(run, "error", None),
    }


def _serving_canonical_lifecycle(
    view: dict[str, Any], canonical: dict[str, Any] | None
) -> dict[str, Any]:
    """The view inspection serves, with the canonical lifecycle winning.

    Under the existing readable-canonical guard, replacement is
    unconditional and includes null (#1036): a stale terminal row over a
    Run the spine holds open serves the open lifecycle (`finished_at` None),
    not the finish the projection invented. Only keys the view already
    carries are replaced, so no new wire fields appear; the stored row keeps
    the lifecycle it recorded (provenance), and only what this door serves
    reflects the canonical Run.
    """
    if canonical is None:
        return view
    served = {
        **view,
        "status": canonical["status"],
        "finished_at": canonical["finished_at"],
    }
    for key in ("result", "error"):
        if key in view:
            served[key] = canonical[key]
    return served


async def list_visible_runs(user_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
    """Recent-run summaries, restricted to the caller's Workspace universe."""
    allowed = await authorized_workspace_ids(user_id)
    visible = [
        summary
        for summary in get_dag_run_store().list_runs(limit=limit)
        if _in_scope(summary, allowed)
    ]
    served: list[dict[str, Any]] = []
    for summary in visible:
        lifecycle = await _canonical_run_lifecycle(str(summary.get("canonical_run_id") or ""))
        served.append(_serving_canonical_lifecycle(summary, lifecycle))
    return served


async def can_inspect_run(user_id: str, run_id: str) -> bool:
    """May `user_id` open this run's detail/event stream?

    Called before the SSE route opens anything: the stream, its replay, and
    every existence signal behind it stay closed until this says yes (#1174).
    """
    record = get_dag_run_store().get_run(run_id)
    if record is None:
        return False
    allowed = await authorized_workspace_ids(user_id)
    return _in_scope(record, allowed)


async def visible_run_detail(user_id: str, run_id: str) -> dict[str, Any] | None:
    """Full detail for one run, or None when it may not be inspected.

    None is the answer for "does not exist" AND for "exists beyond your
    boundary" — deliberately indistinguishable, so a cross-Workspace id gets
    the same 404-shaped refusal a missing id gets and the response confirms
    nothing about runs the caller cannot see (#1174).
    """
    record = get_dag_run_store().get_run(run_id)
    if record is None:
        return None
    allowed = await authorized_workspace_ids(user_id)
    if not _in_scope(record, allowed):
        return None
    lifecycle = await _canonical_run_lifecycle(str(record.get("canonical_run_id") or ""))
    return _serving_canonical_lifecycle(record, lifecycle)


async def visible_run_ids(user_id: str, run_ids: Iterable[str]) -> set[str]:
    """Which of these candidate run ids may `user_id` inspect?

    The list-shaped companion to `visible_run_detail` (the eval-judge verdict
    list reads through it, #1174): the caller's Workspace universe is resolved
    once for the whole batch, and every candidate is answered by the same
    projection-scope rule `visible_run_detail` applies, so a page-level answer
    and a by-id answer can never disagree about what is visible. A candidate
    whose run is missing — or whose projection row carries no Workspace scope
    — is simply absent from the result, exactly as it is invisible to the
    by-id readers.
    """
    allowed = await authorized_workspace_ids(user_id)
    store = get_dag_run_store()
    visible: set[str] = set()
    for run_id in run_ids:
        record = store.get_run(str(run_id))
        if record is not None and _in_scope(record, allowed):
            visible.add(str(run_id))
    return visible
