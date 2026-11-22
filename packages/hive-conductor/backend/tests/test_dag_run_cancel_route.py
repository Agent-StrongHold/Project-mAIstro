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

from maistro.identity import Principal

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) in sys.path:
    sys.path.remove(str(_BACKEND))
sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("integration")]

_USER_ID = "cancel-route-user"


class _ScopedRequest:
    """Just what the dag-runs handlers read off a request: `state.principal`."""

    def __init__(self, user_id: str) -> None:
        self.state = SimpleNamespace(principal=Principal(user_id=user_id, username=user_id))


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


async def _long_running_canonical_run(
    workspace_id: str,
) -> tuple[Any, str, asyncio.Task[Any], asyncio.Event, list[str]]:
    """A canonical Run whose single Attempt's provider is parked mid-flight.

    The provider sleeps on `release` — an event nothing in the product ever
    sets — so the Attempt can only settle if cancellation physically reaches
    it. `provider_exits` records the coroutine actually unwinding, which is
    what distinguishes "the work was stopped" from "the record was edited".
    """
    from services.workspace_authority import canonical_store_for_tests

    from maistro.graph import Graph, Node
    from maistro.runs import AttemptExecutionService, AttemptStatus, InMemoryRunStore
    from maistro.runtime import PythonExecutionRuntime

    # Filed in the caller's own canonical Workspace, as the product files it:
    # the projection overlay reads canonical truth only for a member (#1152).
    project_store = canonical_store_for_tests().project_store
    root = await project_store.root_for_workspace(workspace_id)
    project = await project_store.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name="Long-running DAG",
    )
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project.project_id,
        name="Long-running DAG",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=_USER_ID)
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
    from services.workspace_authority import canonical_store_for_tests

    from maistro.runs.scoped_reads import ScopedRunReader

    store, run_id, worker, release, provider_exits = await _long_running_canonical_run(view.id)
    workspaces = canonical_store_for_tests()
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )

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


async def test_cancel_route_never_writes_projection_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1036 AC-3: cancel/control delegates through #1169 only.

    The public cancel route must not call DagRunStore.finish_run / record_outcome
    / record_status — those would be a second terminalization authority on the
    product-private JsonStore projection. The projection row stays open; the
    inspection overlay serves the spine's CANCELLED.
    """
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from routes.dag_runs import get_run as get_run_route
    from services.dag_run_store import DagRunStore, get_dag_run_store

    from maistro.runs import RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader

    view = await _owned_workspace()
    from services.workspace_authority import canonical_store_for_tests

    store, run_id, worker, release, _provider_exits = await _long_running_canonical_run(view.id)
    workspaces = canonical_store_for_tests()
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )

    projection = get_dag_run_store()
    await projection.start_run(
        run_id="dag-cancel-no-proj-write",
        user_id=_USER_ID,
        workspace_id=view.id,
        canonical_run_id=run_id,
    )

    writes: list[str] = []

    async def _spy_finish(self: Any, *args: Any, **kwargs: Any) -> None:
        writes.append("finish_run")
        raise AssertionError("cancel must not finish the projection")

    async def _spy_outcome(self: Any, *args: Any, **kwargs: Any) -> None:
        writes.append("record_outcome")
        raise AssertionError("cancel must not record_outcome on the projection")

    async def _spy_status(self: Any, *args: Any, **kwargs: Any) -> None:
        writes.append("record_status")
        raise AssertionError("cancel must not record_status on the projection")

    monkeypatch.setattr(DagRunStore, "finish_run", _spy_finish)
    monkeypatch.setattr(DagRunStore, "record_outcome", _spy_outcome)
    monkeypatch.setattr(DagRunStore, "record_status", _spy_status)

    response = await cancel_route("dag-cancel-no-proj-write", _ScopedRequest(_USER_ID))
    assert response["cancelled"] is True
    assert writes == []

    # Raw projection receipt stays open — no product-private finished_at.
    raw = projection.get_run("dag-cancel-no-proj-write")
    assert raw is not None
    assert raw["finished_at"] is None

    # Inspection overlay still follows the canonical cancel.
    detail = await get_run_route("dag-cancel-no-proj-write", _ScopedRequest(_USER_ID))
    assert detail["status"] == "cancelled"
    assert detail["finished_at"] is not None  # canonical Run.finished_at

    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is RunStatus.CANCELLED

    with pytest.raises(asyncio.CancelledError):
        await worker
    assert release.is_set() is False


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


async def test_cancel_route_refuses_while_the_workspace_authority_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authority loss at the mutation gate is 503, not the seam's 404 (#2466).

    The read seam can degrade gracefully -- the projection row was authorized
    through the Workspace authority the request started with -- but by cancel
    time that authority refuses every request (a configured database whose
    Container never started: `EmbeddedRuntimeUnavailable`). Translating that
    into `RunNotVisible`'s 404 would tell an initiator their Run does not
    exist because authorization broke, and would let the same refusal stand
    in for the not-found answer the seam owes absent/foreign targets. The
    route must answer the spine-unavailable 503 instead -- the distinct
    deployment answer `canonical_store_available` already reports to
    readiness for exactly this state.
    """
    import services.engine as engine_mod
    import services.workspace_authority as workspace_authority
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore

    view = await _owned_workspace()

    async def authority_lost() -> Any:
        raise workspace_authority.EmbeddedRuntimeUnavailable(
            "a database is configured but the maistro-core Container holding the "
            "canonical Workspace store is not running"
        )

    # Only the cancel-time authority lookup is lost. Reads keep working
    # through the store the request started with, so what fails below is the
    # mutation gate's re-resolution -- the mid-request loss this pins -- not
    # an unauthorized read (that would answer 404 before the gate runs).
    monkeypatch.setattr(workspace_authority, "canonical_workspace_store", authority_lost)
    # A non-None degraded bridge (run store wired, no scoped reader): with a
    # None run store the route would answer 503 before the gate, and the test
    # would pass for the wrong reason.
    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(
            run_store=InMemoryRunStore(project_store=InMemoryProjectScopeStore()),
            run_reader=None,
        ),
    )
    await get_dag_run_store().start_run(
        run_id="dag-authority-lost",
        user_id=_USER_ID,
        workspace_id=view.id,
    )

    with pytest.raises(HTTPException) as unavailable:
        await cancel_route("dag-authority-lost", _ScopedRequest(_USER_ID))
    assert unavailable.value.status_code == 503
    assert unavailable.value.detail == "canonical execution spine unavailable"


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
    from services.workspace_authority import canonical_store_for_tests

    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore
    from maistro.runs.scoped_reads import ScopedRunReader

    view = await _owned_workspace()
    projects = InMemoryProjectScopeStore()
    empty = InMemoryRunStore(project_store=projects)
    workspaces = canonical_store_for_tests()
    reader = ScopedRunReader(empty, workspaces, projects)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=empty, run_reader=reader)
    )
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


async def test_list_overlays_only_canonical_runs_the_caller_may_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The list path batches its canonical reads through the scoped reader:
    a row naming the caller's own canonical Run shows its status, a row that
    names another Workspace's Run keeps its own (#1152)."""
    import services.engine as engine_mod
    from services.dag_run_inspection import list_visible_runs
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import canonical_store_for_tests

    from maistro.graph import Graph, Node
    from maistro.runs import InMemoryRunStore, RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader

    view = await _owned_workspace()
    workspaces = canonical_store_for_tests()
    projects = workspaces.project_store
    foreign = await workspaces.create(creator_user_id="someone-else", name="Foreign")
    store = InMemoryRunStore(project_store=projects)

    async def cancelled_run(workspace_id: str) -> str:
        root = await projects.root_for_workspace(workspace_id)
        graph = Graph(
            workspace_id=workspace_id,
            project_id=root.project_id,
            name="listed",
            nodes=[Node(node_id="n", node_type="agent")],
        )
        run = await store.create_run(graph, actor_principal_id=_USER_ID)
        await store.transition_run(run.run_id, RunStatus.CANCELLED)
        return run.run_id

    mine, theirs = await cancelled_run(view.id), await cancelled_run(foreign.workspace_id)
    reader = ScopedRunReader(store, workspaces, projects)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    dag_runs = get_dag_run_store()
    await dag_runs.start_run(
        run_id="list-mine", user_id=_USER_ID, workspace_id=view.id, canonical_run_id=mine
    )
    await dag_runs.start_run(
        run_id="list-theirs", user_id=_USER_ID, workspace_id=view.id, canonical_run_id=theirs
    )

    listed = {row["id"]: row for row in await list_visible_runs(_USER_ID, limit=100)}

    assert listed["list-mine"]["status"] == "cancelled"
    assert listed["list-theirs"]["status"] != "cancelled"


async def test_list_resolves_the_page_through_one_batched_reader_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Recent Runs list never re-enters the canonical reader per row (#1333).

    The overlay needs one scoped read for the whole page; a return to the
    pre-#1152 per-row `_canonical_projection` walk shows up here as one
    `get_runs` call per row, each carrying a single id.
    """
    import services.engine as engine_mod
    from services.dag_run_inspection import list_visible_runs
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import canonical_store_for_tests

    from maistro.graph import Graph, Node
    from maistro.runs import InMemoryRunStore
    from maistro.runs.scoped_reads import ScopedRunReader

    view = await _owned_workspace()
    workspaces = canonical_store_for_tests()
    projects = workspaces.project_store
    store = InMemoryRunStore(project_store=projects)

    async def running_run(workspace_id: str) -> str:
        root = await projects.root_for_workspace(workspace_id)
        graph = Graph(
            workspace_id=workspace_id,
            project_id=root.project_id,
            name="listed",
            nodes=[Node(node_id="n", node_type="agent")],
        )
        return (await store.create_run(graph, actor_principal_id=_USER_ID)).run_id

    first, second = await running_run(view.id), await running_run(view.id)
    reader = ScopedRunReader(store, workspaces, projects)
    batches: list[list[str]] = []
    batched_get_runs = reader.get_runs

    async def counting_get_runs(run_ids: Any, *, principal_id: str) -> Any:
        batches.append([str(run_id) for run_id in run_ids])
        return await batched_get_runs(run_ids, principal_id=principal_id)

    reader.get_runs = counting_get_runs  # type: ignore[method-assign]
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    dag_runs = get_dag_run_store()
    await dag_runs.start_run(
        run_id="batched-one", user_id=_USER_ID, workspace_id=view.id, canonical_run_id=first
    )
    await dag_runs.start_run(
        run_id="batched-two", user_id=_USER_ID, workspace_id=view.id, canonical_run_id=second
    )

    listed = await list_visible_runs(_USER_ID, limit=100)

    assert {row["id"] for row in listed} >= {"batched-one", "batched-two"}
    # Exactly one reader call, carrying the whole in-scope page. The process
    # singletons behind these suites keep earlier tests' rows, so the batch may
    # name more than this test's two runs -- but never in more than one call.
    assert len(batches) == 1
    assert {first, second} <= set(batches[0])


# ─── #2466/#1036: view permission never confers cancellation ────────────────
# Cancellation is a lifecycle mutation. The canonical mutation gate
# (`RunStoreBoundary.require_run_mutation`) admits only the Run's initiating
# principal or a Workspace administrator, after enforcing visibility; a
# projection row may not delegate write authority across Workspaces.


async def _member_view(user_id: str, *, role: str = "viewer") -> Any:
    """The suite's owned Workspace with `user_id` added at `role`."""
    from services.workspace_authority import set_member

    view = await _owned_workspace()
    await set_member(view.id, user_id=user_id, role=role)
    return view


def _created_run_store() -> tuple[Any, Any]:
    """A fresh canonical Run store over the shared canonical test Workspace store."""
    from services.workspace_authority import canonical_store_for_tests

    from maistro.runs import InMemoryRunStore

    workspaces = canonical_store_for_tests()
    return InMemoryRunStore(project_store=workspaces.project_store), workspaces


async def _created_canonical_run(
    store: Any, workspaces: Any, workspace_id: str, initiator: str
) -> str:
    """A CREATED canonical Run filed in `workspace_id` by `initiator`."""
    from maistro.graph import Graph, Node

    root = await workspaces.project_store.root_for_workspace(workspace_id)
    graph = Graph(
        workspace_id=workspace_id,
        project_id=root.project_id,
        name="cancel-authority",
        nodes=[Node(node_id="n1", node_type="agent")],
    )
    return (await store.create_run(graph, actor_principal_id=initiator)).run_id


async def test_same_workspace_peer_can_read_but_not_cancel_another_initiator_s_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2466 P0 / #1036 AC: a same-Workspace peer may GET but not cancel.

    Workspace membership admits reads (#1152), never lifecycle mutation: only
    the Run's initiating principal or a Workspace administrator may cancel.
    The peer's refusal is the seam's one non-disclosing 404 -- identical to a
    missing run -- with no Run/NodeRun/Attempt write and no physical provider
    stop signal.
    """
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from routes.dag_runs import get_run as get_run_route
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import canonical_store_for_tests

    from maistro.runs import AttemptStatus, RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader

    peer = "peer-member"
    view = await _member_view(peer)
    store, run_id, worker, release, provider_exits = await _long_running_canonical_run(view.id)
    workspaces = canonical_store_for_tests()
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    await get_dag_run_store().start_run(
        run_id="dag-peer-cancel",
        user_id=_USER_ID,
        workspace_id=view.id,
        canonical_run_id=run_id,
    )

    # The read seam is unchanged: the peer can open the initiator's run.
    detail = await get_run_route("dag-peer-cancel", _ScopedRequest(peer))
    assert detail["id"] == "dag-peer-cancel"
    assert detail["canonical_run_id"] == run_id

    # ...and must not control it. Same 404 a missing id gets, no disclosure.
    with pytest.raises(HTTPException) as refused:
        await cancel_route("dag-peer-cancel", _ScopedRequest(peer))
    assert refused.value.status_code == 404
    assert refused.value.detail == "run not found"

    # No state moved anywhere: the Run is not terminal, the Attempt is still
    # RUNNING, and the provider coroutine never unwound (no stop signal).
    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is not RunStatus.CANCELLED
    node_runs = await store.list_node_runs(run_id)
    attempts = await store.list_attempts(node_runs[0].node_run_id)
    assert attempts and attempts[-1].status is AttemptStatus.RUNNING
    assert provider_exits == []
    assert not worker.done()

    # Deterministic teardown: release the parked provider and unwind.
    release.set()
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker


async def test_workspace_administrator_can_cancel_a_run_the_initiator_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2466: the initiator is not the only canceller. A Workspace
    administrator who did not start the Run may cancel it through the same
    canonical mutation gate maistro-server's route uses -- and the physical
    work still stops."""
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import canonical_store_for_tests

    from maistro.runs import RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader

    admin = "admin-member"
    view = await _member_view(admin, role="owner")
    store, run_id, worker, _release, provider_exits = await _long_running_canonical_run(view.id)
    workspaces = canonical_store_for_tests()
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    await get_dag_run_store().start_run(
        run_id="dag-admin-cancel",
        user_id=_USER_ID,
        workspace_id=view.id,
        canonical_run_id=run_id,
    )

    response = await cancel_route("dag-admin-cancel", _ScopedRequest(admin))
    assert response == {"run_id": run_id, "status": "cancelled", "cancelled": True}
    assert provider_exits == ["provider-stopped"]
    with pytest.raises(asyncio.CancelledError):
        await worker
    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is RunStatus.CANCELLED


async def test_cross_workspace_projection_link_cannot_delegate_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2466: a projection row filed in Workspace X linked to a live canonical
    Run filed in Workspace Y gives an X-only caller no mutation authority over
    Y. The row is visible to the X member -- the read seam says so -- but the
    cancel is the seam's one 404 and the Y Run keeps its state."""
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from routes.dag_runs import get_run as get_run_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader

    peer = "peer-member"
    x_view = await _member_view(peer)
    store, workspaces = _created_run_store()
    linked = await workspaces.create(creator_user_id="y-owner", name="Linked Workspace")
    run_id = await _created_canonical_run(store, workspaces, linked.workspace_id, "y-owner")
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    await get_dag_run_store().start_run(
        run_id="dag-cross-link",
        user_id=_USER_ID,
        workspace_id=x_view.id,
        canonical_run_id=run_id,
    )

    # The read seam shows the X member the row (its own stale presentation).
    detail = await get_run_route("dag-cross-link", _ScopedRequest(peer))
    assert detail["workspace_id"] == x_view.id

    with pytest.raises(HTTPException) as refused:
        await cancel_route("dag-cross-link", _ScopedRequest(peer))
    assert refused.value.status_code == 404
    assert refused.value.detail == "run not found"

    # The linked Y Run never moved: no fence, no terminal state.
    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is RunStatus.CREATED


async def test_cross_workspace_link_refuses_even_an_admin_of_the_run_s_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2466: the projection-to-Run association is enforced even when the
    caller could authorize the mutation against the canonical Run directly.
    A Workspace X row linked to a Workspace Y Run cannot delegate mutation of
    Y -- not even to a principal who administrates Y -- because the route was
    asked through a row whose lifecycle truth the read seam itself refuses to
    attribute (#1152's overlay rule). By the canonical id, the same principal
    gets the ordinary gate answer: allowed."""
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader
    from maistro.workspaces import WorkspaceRole as CanonicalWorkspaceRole

    admin = "peer-member"
    x_view = await _owned_workspace()
    # The caller is an X member, so the read seam serves the row: the refusal
    # below is the mutation gate's, not the read boundary's.
    from services.workspace_authority import set_member

    await set_member(x_view.id, user_id=admin, role="viewer")
    store, workspaces = _created_run_store()
    linked = await workspaces.create(creator_user_id="y-owner", name="Linked Workspace")
    await workspaces.set_membership(
        linked.workspace_id, user_id=admin, role=CanonicalWorkspaceRole.OWNER
    )
    run_id = await _created_canonical_run(store, workspaces, linked.workspace_id, "y-owner")
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    await get_dag_run_store().start_run(
        run_id="dag-cross-admin",
        user_id=_USER_ID,
        workspace_id=x_view.id,
        canonical_run_id=run_id,
    )

    # Through the X row: refused with the seam's one 404.
    with pytest.raises(HTTPException) as refused:
        await cancel_route("dag-cross-admin", _ScopedRequest(admin))
    assert refused.value.status_code == 404
    assert refused.value.detail == "run not found"
    run_after_refused = await store.get_run(run_id)
    assert run_after_refused is not None and run_after_refused.status is RunStatus.CREATED

    # By the canonical id itself: the same principal's Y administration
    # admits the mutation, and the Run settles CANCELLED.
    response = await cancel_route(run_id, _ScopedRequest(admin))
    assert response["cancelled"] is True
    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is RunStatus.CANCELLED


async def test_cancel_by_direct_canonical_id_matches_the_projection_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2466: direct canonical and valid projection IDs behave identically.
    The initiator cancels the same Run once by its canonical id (no projection
    row) and once through a same-Workspace projection row linked to it."""
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader

    view = await _owned_workspace()
    store, workspaces = _created_run_store()
    run_id = await _created_canonical_run(store, workspaces, view.id, _USER_ID)
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )

    direct = await cancel_route(run_id, _ScopedRequest(_USER_ID))
    assert direct == {"run_id": run_id, "status": "cancelled", "cancelled": True}
    assert (await store.get_run(run_id)).status is RunStatus.CANCELLED

    second = await _created_canonical_run(store, workspaces, view.id, _USER_ID)
    await get_dag_run_store().start_run(
        run_id="dag-via-projection",
        user_id=_USER_ID,
        workspace_id=view.id,
        canonical_run_id=second,
    )
    via_projection = await cancel_route("dag-via-projection", _ScopedRequest(_USER_ID))
    assert via_projection == {"run_id": second, "status": "cancelled", "cancelled": True}
    assert (await store.get_run(second)).status is RunStatus.CANCELLED


async def test_cancel_refusal_is_indistinguishable_across_foreign_and_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2466: foreign, forged and absent ids answer the identical 404.
    A stranger who can read nothing, a peer pointed at a forged canonical id,
    and a missing run all get the same non-disclosing refusal."""
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.scoped_reads import ScopedRunReader

    stranger = "stranger-user"
    view = await _owned_workspace()
    store, workspaces = _created_run_store()
    run_id = await _created_canonical_run(store, workspaces, view.id, _USER_ID)
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    await get_dag_run_store().start_run(
        run_id="dag-foreign-forged",
        user_id=_USER_ID,
        workspace_id=view.id,
        canonical_run_id="canonical-forged-id",
    )

    refusals = []
    for caller, target in (
        (stranger, "dag-foreign-forged"),  # foreign principal on a real row
        (_USER_ID, "dag-never-was"),  # unknown id
        (_USER_ID, "dag-foreign-forged"),  # forged canonical link, valid row
    ):
        with pytest.raises(HTTPException) as refused:
            await cancel_route(target, _ScopedRequest(caller))
        refusals.append((refused.value.status_code, refused.value.detail))

    assert refusals == [(404, "run not found"), (404, "run not found"), (404, "run not found")]
    # The real Run behind the forged link was never touched.
    from maistro.runs import RunStatus

    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is not RunStatus.CANCELLED


async def test_cancel_gate_resolves_the_run_through_the_wired_reader_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2466: the mutation gate resolves through the stores the read used.

    `visible_run_detail` authorized this initiator through the engine
    bridge's wired reader (its own Workspace/Project authorities); the gate
    must resolve the target through that same triple. Re-deriving a second
    authority -- the embedded fallback Workspace store's default Project
    store -- 404s the initiator's cancel whenever the execution spine wires
    its own Project scope store (the cross-product parity profile): the
    re-derived store has never heard of the Run's Project, so the gate's
    scoped read answers RunNotVisible for a Run the same principal just
    read.
    """
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.workspace_authority import canonical_store_for_tests

    from maistro.graph import Graph, Node
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore, RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader

    view = await _owned_workspace()
    # The spine's own Project store -- a distinct authority from the
    # Workspace store's bound default, exactly as `wire_execution_spine`
    # composes it for an embedded producer.
    spine_projects = InMemoryProjectScopeStore()
    root = await spine_projects.create_root(view.id)
    project = await spine_projects.create(
        workspace_id=view.id,
        parent_project_id=root.project_id,
        name="Parity turn",
    )
    store = InMemoryRunStore(project_store=spine_projects)
    graph = Graph(
        workspace_id=view.id,
        project_id=project.project_id,
        name="Parity turn",
        nodes=[Node(node_id="n1", node_type="agent")],
    )
    run_id = (await store.create_run(graph, actor_principal_id=_USER_ID)).run_id
    reader = ScopedRunReader(store, canonical_store_for_tests(), spine_projects)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )

    # The initiator who can read the Run can cancel it: the gate answers
    # from the spine's own truth, not from a store that cannot see it.
    response = await cancel_route(run_id, _ScopedRequest(_USER_ID))
    assert response == {"run_id": run_id, "status": "cancelled", "cancelled": True}
    cancelled = await store.get_run(run_id)
    assert cancelled is not None and cancelled.status is RunStatus.CANCELLED
