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
from datetime import datetime
from typing import Any

from maistro.runs.model import RunStatus
from services.dag_run_store import get_dag_run_store
from services.workspace_authority import list_views_for_user


def _canonical_run_store() -> Any | None:
    """Return the canonical RunStore, or None in standalone compatibility mode."""
    try:
        from services.dag_agents import _container

        container = _container()
    except Exception:  # pragma: no cover - boot-time compatibility path
        return None
    if container is None:
        return None
    return container.run_store


def _timestamp(value: datetime | None) -> float | None:
    return value.timestamp() if value is not None else None


async def _canonical_snapshot(run_id: str) -> tuple[Any, list[Any], list[Any]] | None:
    """Read current canonical Run/NodeRun/Attempt facts by canonical id.

    The graph durable store is only a compatibility fallback for standalone
    Hive. In a booted Container, the canonical RunStore is always consulted
    first; a stale DagRunStore row can therefore never win a read.
    """
    if not run_id:
        return None
    store = _canonical_run_store()
    if store is not None:
        run = await store.get_run(run_id)
        if run is None:
            return None
        node_runs = await store.list_node_runs(run_id)
        attempts: list[Any] = []
        for node_run in node_runs:
            attempts.extend(await store.list_attempts(node_run.node_run_id))
        return run, node_runs, attempts

    # A standalone process has no canonical RunStore, but the durable graph
    # adapter still carries the same Run/NodeRun/Attempt record in memory.
    try:
        from services.dag_agents import get_run_store

        record = await get_run_store().get(run_id)
    except Exception:  # pragma: no cover - compatibility fallback
        return None
    if record is None:
        return None
    return record.run, list(record.node_runs), list(record.attempts)


async def _canonical_runs(limit: int) -> list[tuple[Any, list[Any], list[Any]]]:
    """List canonical Runs across every lifecycle state for inspection."""
    store = _canonical_run_store()
    if store is None:
        return []
    found: dict[str, tuple[Any, list[Any], list[Any]]] = {}
    for status in RunStatus:
        for run in await store.list_by_status(status, limit=limit):
            snapshot = await _canonical_snapshot(run.run_id)
            if snapshot is not None:
                found[run.run_id] = snapshot
    return sorted(
        found.values(),
        key=lambda item: item[0].created_at,
        reverse=True,
    )[:limit]


def _node_states(node_runs: list[Any]) -> dict[str, str]:
    return {node_run.node_id: node_run.status.value for node_run in node_runs}


def _canonical_summary(
    run: Any, node_runs: list[Any], projection: dict[str, Any] | None
) -> dict[str, Any]:
    """Adapt canonical lifecycle facts to the established Conductor shape."""
    summary = dict(projection or {})
    summary.update(
        {
            "id": run.run_id,
            "canonical_run_id": run.run_id,
            "workspace_id": run.workspace_id,
            "project_id": run.project_id,
            "dag_id": summary.get("dag_id") or run.graph.graph_id,
            "status": run.status.value,
            "started_at": _timestamp(run.started_at) or _timestamp(run.created_at),
            "finished_at": _timestamp(run.finished_at),
            "event_count": int(summary.get("event_count") or 0),
            "node_states": _node_states(node_runs),
        }
    )
    return summary


async def _canonical_detail(
    run: Any,
    node_runs: list[Any],
    attempts: list[Any],
    projection: dict[str, Any] | None,
) -> dict[str, Any]:
    detail = _canonical_summary(run, node_runs, projection)
    detail.update(
        {
            "result": run.result,
            "error": run.error,
            "events": list((projection or {}).get("events") or []),
            # These are read-only adapters over canonical records, not a
            # second lifecycle representation. JSON mode also converts enums
            # and datetimes for callers that use this service directly.
            "node_runs": [node_run.model_dump(mode="json") for node_run in node_runs],
            "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
        }
    )
    return detail


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
    """Recent summaries from canonical Runs, with history as presentation only."""
    allowed = await authorized_workspace_ids(user_id)
    history = get_dag_run_store()
    projections = {row["id"]: row for row in history.list_runs(limit=limit)}
    canonical = await _canonical_runs(limit)
    results: dict[str, dict[str, Any]] = {}

    # Canonical Runs are listed even when a producer has not emitted a
    # Conductor history row. This keeps every producer on one inspection plane.
    for run, node_runs, _attempts in canonical:
        if run.workspace_id in allowed:
            projection = projections.get(run.run_id) or history.get_run(run.run_id)
            results[run.run_id] = _canonical_summary(run, node_runs, projection)

    # Pre-convergence rows remain readable, but a canonical row always wins.
    for row in projections.values():
        canonical_id = str(row.get("canonical_run_id") or row.get("id") or "")
        if canonical_id in results:
            continue
        snapshot = await _canonical_snapshot(canonical_id)
        if snapshot is not None:
            run, node_runs, _attempts = snapshot
            if run.workspace_id in allowed:
                results[run.run_id] = _canonical_summary(run, node_runs, row)
        elif _in_scope(row, allowed) and not (
            row.get("canonical_run_id") and _canonical_run_store() is not None
        ):
            results[str(row["id"])] = row

    return sorted(
        results.values(),
        key=lambda row: float(row.get("started_at") or 0),
        reverse=True,
    )[:limit]


async def _visible_snapshot(
    user_id: str, run_id: str
) -> tuple[Any, list[Any], list[Any], dict[str, Any] | None] | None:
    """Resolve a requested id to canonical facts before checking visibility."""
    history = get_dag_run_store()
    projection = history.get_run(run_id)
    canonical_id = str((projection or {}).get("canonical_run_id") or run_id)
    snapshot = await _canonical_snapshot(canonical_id)
    if snapshot is None:
        if projection is None:
            return None
        # Once a Container owns the canonical store, a row that names a
        # canonical Run is not a fallback record. Hiding it on a missing
        # canonical identity prevents restart/purge residue from resurrecting
        # product-private terminal truth.
        if projection.get("canonical_run_id") and _canonical_run_store() is not None:
            return None
        allowed = await authorized_workspace_ids(user_id)
        return (None, [], [], projection) if _in_scope(projection, allowed) else None

    run, node_runs, attempts = snapshot
    allowed = await authorized_workspace_ids(user_id)
    if run.workspace_id not in allowed:
        return None
    return run, node_runs, attempts, projection or history.get_run(canonical_id)


async def can_inspect_run(user_id: str, run_id: str) -> bool:
    """May `user_id` open this run's detail/event stream?"""
    return await _visible_snapshot(user_id, run_id) is not None


async def visible_run_detail(user_id: str, run_id: str) -> dict[str, Any] | None:
    """Full detail for one run, or None when it may not be inspected.

    None is the answer for "does not exist" AND for "exists beyond your
    boundary" — deliberately indistinguishable, so a cross-Workspace id gets
    the same 404-shaped refusal a missing id gets and the response confirms
    nothing about runs the caller cannot see (#1174).
    """
    resolved = await _visible_snapshot(user_id, run_id)
    if resolved is None:
        return None
    run, node_runs, attempts, projection = resolved
    if run is None:
        return projection
    return await _canonical_detail(run, node_runs, attempts, projection)


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
    for candidate in run_ids:
        run_id = str(candidate)
        projection = store.get_run(run_id)
        canonical_id = str((projection or {}).get("canonical_run_id") or run_id)
        snapshot = await _canonical_snapshot(canonical_id)
        if snapshot is not None:
            if snapshot[0].workspace_id in allowed:
                visible.add(run_id)
        elif (
            projection is not None
            and _in_scope(projection, allowed)
            and not (projection.get("canonical_run_id") and _canonical_run_store() is not None)
        ):
            visible.add(run_id)
    return visible
