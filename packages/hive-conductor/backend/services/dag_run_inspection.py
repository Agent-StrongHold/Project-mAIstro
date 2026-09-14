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

from services.dag_run_store import MAX_EVENTS_PER_RUN, MAX_RUNS, get_dag_run_store
from services.workspace_authority import list_views_for_user


# Routes use these helpers instead of importing projection storage directly.
# The projection remains an observation/event buffer; canonical Run state is
# resolved by this module's inspection functions.
def projection_store() -> Any:
    return get_dag_run_store()


def retention_metadata() -> dict[str, Any]:
    store = get_dag_run_store()
    return {
        "durable": store.is_durable,
        "max_runs": MAX_RUNS,
        "max_events_per_run": MAX_EVENTS_PER_RUN,
    }


def _canonical_store() -> Any | None:
    """Return the configured canonical Run store, or None in standalone mode."""
    try:
        from services.engine import get_engine

        return get_engine().run_store
    except Exception:
        return None


async def _canonical_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Overlay lifecycle truth from the canonical Run, when this deployment has one."""
    run_id = str(record.get("canonical_run_id") or record.get("id") or "")
    if not run_id:
        return record
    store = _canonical_store()
    try:
        run = await store.get_run(run_id) if store is not None else None
    except Exception:
        # Projection reads remain available in standalone mode, but never
        # invent canonical status when the spine is unavailable.
        return record
    if run is None:
        return record
    return {
        **record,
        "status": run.status.value,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "run_id": run.run_id,
        "canonical_run_id": run.run_id,
        **({"result": run.result} if run.result is not None else {}),
        **({"error": run.error} if run.error else {}),
    }


async def _canonical_record(run: Any) -> dict[str, Any]:
    """Build an inspection record from canonical Run state plus observations."""
    projected = get_dag_run_store().get_run(run.run_id)
    if projected is not None:
        return await _canonical_projection(projected)
    canonical_store = _canonical_store()
    assert canonical_store is not None
    node_runs = await canonical_store.list_node_runs(run.run_id)
    return {
        "id": run.run_id,
        "run_id": run.run_id,
        "canonical_run_id": run.run_id,
        "dag_id": run.graph.graph_id,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "status": run.status.value,
        "started_at": run.started_at.timestamp() if run.started_at else None,
        "finished_at": run.finished_at.timestamp() if run.finished_at else None,
        "event_count": 0,
        "node_states": {item.node_id: item.status.value for item in node_runs},
        "events": [],
    }


async def _canonical_runs(allowed: set[str]) -> list[dict[str, Any]] | None:
    """List canonical Runs when the process is configured with the spine.

    None means standalone mode and deliberately selects the compatibility
    projection path. Once a canonical store is configured, a projection row
    cannot create, hide, or terminalize a Run for this observer.
    """
    store = _canonical_store()
    if store is None:
        return None
    from maistro.runs.model import RunStatus

    runs: dict[str, Any] = {}
    for status in RunStatus:
        for run in await store.list_by_status(status, limit=MAX_RUNS, workspace_id=None):
            if run.workspace_id in allowed:
                runs[run.run_id] = run
    ordered = sorted(runs.values(), key=lambda run: run.created_at, reverse=True)
    return [await _canonical_record(run) for run in ordered[:MAX_RUNS]]


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
    # Fetch the complete retained window before applying the caller's limit.
    # Limiting the global projection first lets a burst of foreign runs hide a
    # caller's own older run (or return an empty page), even though it is in
    # scope. Filtering first preserves normal pagination semantics without
    # exposing any additional rows. Each surviving summary is overlaid with
    # canonical execution truth before the caller's limit is applied.
    canonical = await _canonical_runs(allowed)
    if canonical is not None:
        return canonical[:limit]

    visible = [
        await _canonical_projection(summary)
        for summary in get_dag_run_store().list_runs(limit=MAX_RUNS)
        if _in_scope(summary, allowed)
    ]
    return visible[:limit]


async def can_inspect_run(user_id: str, run_id: str) -> bool:
    """May `user_id` open this run's detail/event stream?

    Called before the SSE route opens anything: the stream, its replay, and
    every existence signal behind it stay closed until this says yes (#1174).
    """
    store = _canonical_store()
    if store is not None:
        projection = get_dag_run_store().get_run(run_id)
        canonical_id = str((projection or {}).get("canonical_run_id") or run_id)
        run = await store.get_run(canonical_id)
        if run is None:
            return False
        allowed = await authorized_workspace_ids(user_id)
        # Canonical scope is the only authorization input once the spine is
        # configured. A stale or malicious projection cannot widen it, even
        # when its copied Workspace disagrees with the Run.
        return run.workspace_id in allowed

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
    store = _canonical_store()
    if store is not None:
        projection = get_dag_run_store().get_run(run_id)
        canonical_id = str((projection or {}).get("canonical_run_id") or run_id)
        run = await store.get_run(canonical_id)
        if run is None:
            return None
        allowed = await authorized_workspace_ids(user_id)
        if run.workspace_id not in allowed:
            return None
        return await _canonical_record(run)

    record = get_dag_run_store().get_run(run_id)
    if record is None:
        return None
    allowed = await authorized_workspace_ids(user_id)
    if not _in_scope(record, allowed):
        return None
    return await _canonical_projection(record)


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
    canonical_store = _canonical_store()
    if canonical_store is not None:
        visible: set[str] = set()
        projections = get_dag_run_store()
        for run_id in run_ids:
            candidate = str(run_id)
            projection = projections.get_run(candidate)
            canonical_id = str((projection or {}).get("canonical_run_id") or candidate)
            run = await canonical_store.get_run(canonical_id)
            if run is not None and run.workspace_id in allowed:
                visible.add(candidate)
        return visible

    store = get_dag_run_store()
    visible = set()
    for run_id in run_ids:
        record = store.get_run(str(run_id))
        if record is not None and _in_scope(record, allowed):
            visible.add(str(run_id))
    return visible
