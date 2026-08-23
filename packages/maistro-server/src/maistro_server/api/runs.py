"""Reading the canonical Run a task was admitted as (#41).

`POST /tasks` returns a `run_id` and calls it the identity to follow. Without
somewhere to follow it to, that is an advertised handle with nothing behind it —
worse than not returning one, because a client can build on it.

Deliberately read-only. A Run's lifecycle is driven by the execution spine, not
by HTTP: a `PATCH /runs/{id}` would be a second way to move canonical state and
put us back where #41 started.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from maistro.runs.store import RunStore
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal
from maistro_server.api.schemas import NodeRunSummary, RunSummary

router = APIRouter(prefix="/runs", tags=["runs"])

_run_store: RunStore | None = None


def configure_run_store(store: RunStore | None) -> None:
    """Install the store the routes read, from the app lifespan."""
    global _run_store
    _run_store = store


def get_run_store() -> RunStore:
    if _run_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Run store is configured",
        )
    return _run_store


def _owner_id(auth: AuthenticatedPrincipal | None) -> str:
    """Mirrors `tasks._owner_id`: "dev" only where auth is disabled entirely."""
    if auth is None:
        return "dev"
    return auth.user_id


async def _require_visible_run(store: RunStore, run_id: str, owner: str) -> Any:
    """Fetch a Run the caller is allowed to see, or 404.

    404 rather than 403 on a scope mismatch, deliberately: a 403 confirms the
    run_id exists, which is exactly what an enumeration attempt is asking.

    A Run with no `actor_principal_id` is visible to nobody but the unauthenticated
    "dev" principal — the same fail-closed rule `TaskQueue.get` had to be fixed
    into, where `task.user_id and ...` short-circuited on the empty string and
    handed ownerless tasks to every caller.
    """
    run = await store.get_run(run_id)
    if run is None or (run.actor_principal_id or "dev") != owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    auth: RequireAuth,
    store: Annotated[RunStore, Depends(get_run_store)],
) -> RunSummary:
    """The canonical execution state behind a submitted task."""
    run = await _require_visible_run(store, run_id, _owner_id(auth))
    return RunSummary(
        run_id=run.run_id,
        status=run.status.value,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        graph_id=run.graph.graph_id,
        provenance=dict(run.provenance),
        created_at=run.created_at,
        finished_at=run.finished_at,
        result=run.result,
        error=run.error,
    )


@router.get("/{run_id}/node-runs")
async def list_node_runs(
    run_id: str,
    auth: RequireAuth,
    store: Annotated[RunStore, Depends(get_run_store)],
) -> list[NodeRunSummary]:
    """Per-node execution state under a Run.

    Empty until the Run's work actually executes, and populated once it does
    (#143): a task's execution now goes through the canonical Attempt seam, so
    the node it was admitted over has a real NodeRun and at least one Attempt.
    Still empty for a Run whose work has not been picked up, which is the true
    answer rather than an advertised gap.
    """
    await _require_visible_run(store, run_id, _owner_id(auth))
    return [
        NodeRunSummary(
            node_run_id=node_run.node_run_id,
            node_id=node_run.node_id,
            status=node_run.status.value,
            created_at=node_run.created_at,
            finished_at=node_run.finished_at,
        )
        for node_run in await store.list_node_runs(run_id)
    ]
