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
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from services.dag_run_store import get_dag_run_store
from services.workspace_authority import list_views_for_user


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


async def list_visible_runs(user_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
    """Recent-run summaries, restricted to the caller's Workspace universe."""
    allowed = await authorized_workspace_ids(user_id)
    return [
        summary
        for summary in get_dag_run_store().list_runs(limit=limit)
        if _in_scope(summary, allowed)
    ]


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
    return record


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
