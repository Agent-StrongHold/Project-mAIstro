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


def _canonical_run_store() -> Any | None:
    """Return the configured canonical RunStore, or None in standalone mode.

    The DAG history store remains a presentation projection for its event log,
    but it is never consulted for canonical identity or lifecycle when the
    product has a wired execution spine.
    """
    try:
        from services.engine import get_engine

        return get_engine().run_store
    except Exception:
        # Inspection must remain importable while the optional core bridge is
        # unavailable; callers then use the explicit standalone projection
        # compatibility path below.
        return None


def _timestamp(value: Any) -> float | None:
    return value.timestamp() if value is not None else None


def _canonical_summary(run: Any, *, node_runs: list[Any]) -> dict[str, Any]:
    node_states = {node.node_id: node.status.value for node in node_runs}
    provenance = dict(run.provenance)
    return {
        "id": run.run_id,
        "run_id": run.run_id,
        "user_id": run.actor_principal_id or "",
        "dag_id": provenance.get("legacy_dag_id") or run.graph.graph_id,
        "status": run.status.value,
        "canonical_run_id": run.run_id,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "started_at": _timestamp(run.started_at),
        "finished_at": _timestamp(run.finished_at),
        "event_count": 0,
        "node_states": node_states,
    }


async def _canonical_detail(run: Any, store: Any) -> dict[str, Any]:
    node_runs = await store.list_node_runs(run.run_id)
    attempts: list[Any] = []
    for node_run in node_runs:
        attempts.extend(await store.list_attempts(node_run.node_run_id))

    detail = _canonical_summary(run, node_runs=node_runs)
    detail.update(
        {
            "graph": {
                "graph_id": run.graph.graph_id,
                "workspace_id": run.graph.workspace_id,
                "project_id": run.graph.project_id,
                "content_hash": run.graph.content_hash,
                "definition_json": run.graph.definition_json,
            },
            "node_runs": [node_run.model_dump(mode="json") for node_run in node_runs],
            "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
            "result": run.result,
            "error": run.error,
            "events": [],
        }
    )

    # Events are a UI projection only. If one exists, include it without using
    # its status or IDs to answer the canonical inspection request.
    projection = get_dag_run_store().get_run(run.run_id)
    if projection is not None:
        detail["events"] = projection.get("events", [])
        detail["event_count"] = len(detail["events"])
    return detail


async def _visible_canonical_run(user_id: str, run_id: str) -> tuple[Any, Any] | None:
    store = _canonical_run_store()
    if store is None:
        return None
    run = await store.get_run(run_id)
    if run is None:
        return None
    if run.workspace_id not in await authorized_workspace_ids(user_id):
        return None
    return run, store


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
    """Recent canonical Run summaries, restricted to the caller's Workspace."""
    store = _canonical_run_store()
    if store is not None:
        # RunStore has a status-indexed query rather than a global list. Read
        # each status through that canonical index, then apply one presentation
        # ordering after scope filtering.
        candidates: dict[str, Any] = {}
        from maistro.runs.model import RunStatus

        for status in RunStatus:
            for run in await store.list_by_status(status, limit=max(limit, 100)):
                candidates[run.run_id] = run
        visible = [
            run
            for run in candidates.values()
            if run.workspace_id in await authorized_workspace_ids(user_id)
        ]
        visible.sort(key=lambda run: run.created_at, reverse=True)
        summaries: list[dict[str, Any]] = []
        for run in visible[:limit]:
            summaries.append(
                _canonical_summary(run, node_runs=await store.list_node_runs(run.run_id))
            )
        return summaries

    # Standalone Conductor deployments have no canonical bridge. Keep the
    # historical projection readable there, but never use it when a canonical
    # RunStore exists (the product path cannot silently disagree with Run).
    allowed = await authorized_workspace_ids(user_id)
    return [
        summary
        for summary in get_dag_run_store().list_runs(limit=limit)
        if _in_scope(summary, allowed)
    ]


async def can_inspect_run(user_id: str, run_id: str) -> bool:
    """May `user_id` open this run's detail/event stream?"""
    canonical = await _visible_canonical_run(user_id, run_id)
    if canonical is not None:
        return True
    if _canonical_run_store() is not None:
        return False
    record = get_dag_run_store().get_run(run_id)
    if record is None:
        return False
    allowed = await authorized_workspace_ids(user_id)
    return _in_scope(record, allowed)


async def visible_run_detail(user_id: str, run_id: str) -> dict[str, Any] | None:
    """Return canonical Run/NodeRun/Attempt evidence for an authorized run.

    A projection is used only when this process has no canonical bridge. Once
    the bridge exists, a missing canonical Run is a missing run, even if stale
    product history happens to retain the same string id.
    """
    canonical = await _visible_canonical_run(user_id, run_id)
    if canonical is not None:
        run, store = canonical
        return await _canonical_detail(run, store)
    if _canonical_run_store() is not None:
        return None
    record = get_dag_run_store().get_run(run_id)
    if record is None:
        return None
    allowed = await authorized_workspace_ids(user_id)
    if not _in_scope(record, allowed):
        return None
    return record


async def cancel_visible_run(user_id: str, run_id: str) -> dict[str, Any] | None:
    """Cancel an authorized canonical Run and return its new canonical view."""
    canonical = await _visible_canonical_run(user_id, run_id)
    if canonical is None:
        return None
    run, store = canonical
    from maistro.runs.model import RunStatus

    if run.status not in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }:
        run = await store.transition_run(
            run_id,
            RunStatus.CANCELLED,
            error=f"cancelled by principal {user_id}",
        )
    return await _canonical_detail(run, store)


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
    store = _canonical_run_store()
    if store is not None:
        allowed = await authorized_workspace_ids(user_id)
        visible: set[str] = set()
        for run_id in run_ids:
            run = await store.get_run(str(run_id))
            if run is not None and run.workspace_id in allowed:
                visible.add(str(run_id))
        return visible

    allowed = await authorized_workspace_ids(user_id)
    projection_store = get_dag_run_store()
    visible = set()
    for run_id in run_ids:
        record = projection_store.get_run(str(run_id))
        if record is not None and _in_scope(record, allowed):
            visible.add(str(run_id))
    return visible
