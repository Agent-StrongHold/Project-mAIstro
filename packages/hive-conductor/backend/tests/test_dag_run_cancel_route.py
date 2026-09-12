"""AC8 (#1169): the shipped Conductor cancel route stops canonical physical work.

POST /v1/dag-runs/{run_id}/cancel must not merely edit the projection row:
it has to reach the canonical Run spine, persist the durable CANCELLED fence,
and terminate the provider work an in-process Runtime owns — the same control
the server API and the task queue delegate to. A long-running DAG whose node
is genuinely mid-flight is the case that earns the route's existence: a
cancel that only rewrote projections would leave the provider running with
nothing able to tell.

The suite drives the route handler exactly as AuthMiddleware would deliver a
request to it (the fabricated-Request style of test_dag_run_scope.py) against
a real `InMemoryRunStore`, with the engine's canonical `run_store` bridge
pointed at that store. Without the bridge the route refuses with 503 — that
refusal is pinned too, because "canonical execution spine unavailable" is a
real deployment answer rather than an error to paper over.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) in sys.path:
    sys.path.remove(str(_BACKEND))
sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("integration")]

_USER_ID = "cancel-route-user"


class _ScopedRequest:
    """Just what the dag-runs handlers read off a request: `state.user`."""

    def __init__(self, user_id: str) -> None:
        self.state = SimpleNamespace(user={"id": user_id, "username": user_id})


async def _owned_workspace() -> Any:
    from services.workspace_authority import create_workspace

    return await create_workspace(
        creator_user_id=_USER_ID,
        name="Cancel Route",
        persona_template_id="pm_fleet",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )


async def _long_running_canonical_run() -> tuple[
    Any, str, asyncio.Task[Any], asyncio.Event, list[str]
]:
    """A canonical Run whose single Attempt's provider is parked mid-flight.

    The provider sleeps on `release` — an event nothing in the product ever
    sets — so the Attempt can only settle if cancellation physically reaches
    it. `provider_exits` records the coroutine actually unwinding, which is
    what distinguishes "the work was stopped" from "the record was edited".
    """
    from maistro.graph import Graph, Node
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import AttemptExecutionService, AttemptStatus, InMemoryRunStore
    from maistro.runtime import PythonExecutionRuntime

    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-cancel")
    project = await project_store.create(
        workspace_id="ws-cancel",
        parent_project_id=root.project_id,
        name="Long-running DAG",
    )
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-cancel",
        project_id=project.project_id,
        name="Long-running DAG",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")

    provider_exits: list[str] = []
    release = asyncio.Event()

    async def provider(work_item: Any, context: Any) -> Any:
        try:
            await release.wait()
            return "finished"  # pragma: no cover - never reached while cancelled
        finally:
            provider_exits.append("provider-stopped")

    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    worker = asyncio.create_task(
        service.execute(
            node_run.node_run_id,
            {"prompt": "long work"},
            SimpleNamespace(),
            executor=provider,
        )
    )
    # Deterministic mid-flight: wait until the Attempt is durably RUNNING, then
    # give the loop the ticks it needs to park the provider on `release`. The
    # worker can never finish on its own — nothing sets the event.
    for _ in range(500):
        attempts = await store.list_attempts(node_run.node_run_id)
        if attempts and attempts[-1].status is AttemptStatus.RUNNING:
            break
        await asyncio.sleep(0.01)
    else:  # pragma: no cover - setup failure, not the behavior under test
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        pytest.fail("Attempt never reached RUNNING")
    for _ in range(10):
        if worker.done():  # pragma: no cover - nothing sets the release event
            pytest.fail("worker finished without its provider being released")
        await asyncio.sleep(0)
    return store, run.run_id, worker, release, provider_exits


async def test_cancel_route_terminates_a_long_running_canonical_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from routes.dag_runs import get_run as get_run_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import AttemptStatus, RunStatus

    view = await _owned_workspace()
    store, run_id, worker, release, provider_exits = await _long_running_canonical_run()
    monkeypatch.setattr(engine_mod, "_singleton", SimpleNamespace(run_store=store))

    await get_dag_run_store().start_run(
        run_id="dag-cancel-e2e",
        user_id=_USER_ID,
        workspace_id=view.id,
        canonical_run_id=run_id,
    )

    response = await cancel_route("dag-cancel-e2e", _ScopedRequest(_USER_ID))
    assert response == {"run_id": run_id, "status": "cancelled", "cancelled": True}

    # The physical work is over: the provider coroutine unwound (its finally
    # ran), and the AttemptExecutionService task settled as cancelled rather
    # than publishing a success for work that was stopped.
    assert provider_exits == ["provider-stopped"]
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert release.is_set() is False

    # The durable record agrees, at every altitude: Run, NodeRun, Attempt.
    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is RunStatus.CANCELLED
    node_runs = await store.list_node_runs(run_id)
    assert node_runs and all(nr.status is RunStatus.CANCELLED for nr in node_runs)
    attempts = await store.list_attempts(node_runs[0].node_run_id)
    assert attempts and attempts[-1].status is AttemptStatus.CANCELLED

    # And the projection reads canonical truth, not its own stale row.
    detail = await get_run_route("dag-cancel-e2e", _ScopedRequest(_USER_ID))
    assert detail["status"] == "cancelled"


async def test_cancel_route_refuses_while_the_spine_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    view = await _owned_workspace()
    monkeypatch.setattr(engine_mod, "_singleton", SimpleNamespace(run_store=None))
    await get_dag_run_store().start_run(
        run_id="dag-no-spine",
        user_id=_USER_ID,
        workspace_id=view.id,
    )

    with pytest.raises(HTTPException) as refused:
        await cancel_route("dag-no-spine", _ScopedRequest(_USER_ID))
    assert refused.value.status_code == 503


async def test_cancel_route_answers_a_missing_run_with_a_scoped_404() -> None:
    from routes.dag_runs import cancel_run as cancel_route

    with pytest.raises(HTTPException) as refused:
        await cancel_route("dag-never-was", _ScopedRequest(_USER_ID))
    assert refused.value.status_code == 404


async def test_cancel_route_answers_a_canonical_run_the_spine_never_saw_with_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A projection pointing at a canonical Run that no longer exists is 404.

    The DAG row exists, so the scoped detail lookup succeeds — the miss is on
    the canonical side, and the route must answer in the caller's terms
    rather than leaking the spine's ValueError.
    """
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore

    view = await _owned_workspace()
    empty = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
    monkeypatch.setattr(engine_mod, "_singleton", SimpleNamespace(run_store=empty))
    await get_dag_run_store().start_run(
        run_id="dag-ghost-canonical",
        user_id=_USER_ID,
        workspace_id=view.id,
        canonical_run_id="canonical-never-was",
    )

    with pytest.raises(HTTPException) as refused:
        await cancel_route("dag-ghost-canonical", _ScopedRequest(_USER_ID))
    assert refused.value.status_code == 404
    assert refused.value.detail == "run not found"
