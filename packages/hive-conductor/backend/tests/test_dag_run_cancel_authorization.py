"""POST /v1/dag-runs/{id}/cancel must clear the canonical mutation boundary (#2466).

Read visibility (`services.dag_run_inspection.visible_run_detail`) admits every
Workspace member (#1152: membership admits reads, never writes). Cancellation
is a lifecycle mutation, so before #2466 the shipped Conductor route — which
checked only that read seam and then called `RunExecutionService.cancel_run`
directly — let an ordinary peer member cancel another principal's live Run,
and let a projection row in one Workspace delegate cancellation of a canonical
Run filed in another. The fix answers through the same canonical gate
maistro-server's cancel route uses (`RunStoreBoundary.require_run_mutation`,
pinned there by `test_task_workspace_scope.py::
test_cancel_stays_with_the_initiator_or_an_administrator`), so both routes
diverge never: initiator or Workspace administrator, one refusal shape.

The suite drives the route handler exactly as AuthMiddleware would deliver a
request to it (the fabricated-Request style of test_dag_run_cancel_route.py)
against a real `InMemoryRunStore` with the provider parked mid-flight, so
every refusal is checked against the *physical* path — no canonical
transition, no provider unwind — not merely the response code. The
transition spy records the store's own `transition_run` (the durable CANCELLED
fence), proving a denial is not a response suppressed after the mutation.
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

_INITIATOR = "cancel-auth-initiator"  # member A: starts the Runs
_PEER = "cancel-auth-peer"  # member B: same Workspace, ordinary member
_ADMIN = "cancel-auth-admin"  # C: Workspace administrator, never initiated
_X_OWNER = "cancel-auth-row-owner"  # owns the Workspace a cross-link row lives in
_Y_OWNER = "cancel-auth-run-owner"  # owns the Workspace the linked Run lives in
_OUTSIDER = "cancel-auth-outsider"  # no membership in any relevant Workspace


class _ScopedRequest:
    """Just what the dag-runs handlers read off a request: `state.principal`."""

    def __init__(self, user_id: str) -> None:
        self.state = SimpleNamespace(principal=Principal(user_id=user_id, username=user_id))


async def _workspace(name: str, creator: str) -> Any:
    from services.workspace_authority import create_workspace

    return await create_workspace(
        creator_user_id=creator,
        name=name,
        persona_template_id="pm_fleet",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )


async def _grant_member(workspace_id: str, user_id: str, role: Any) -> None:
    from services.workspace_authority import canonical_store_for_tests

    await canonical_store_for_tests().set_membership(workspace_id, user_id=user_id, role=role)


def _engine_at(monkeypatch: pytest.MonkeyPatch, store: Any, reader: Any) -> None:
    import services.engine as engine_mod

    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )


def _transition_spy(store: Any, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every durable Run transition the cancel path attempts.

    A denial must precede the mutation, not merely hide its response: after a
    refused cancel this list has to stay empty.
    """
    transitions: list[str] = []
    original = type(store).transition_run

    async def _spy(self: Any, run_id: str, status: Any, **kwargs: Any) -> Any:
        transitions.append(f"{run_id}->{getattr(status, 'value', status)}")
        return await original(self, run_id, status, **kwargs)

    monkeypatch.setattr(type(store), "transition_run", _spy)
    return transitions


async def _parked_run(workspace_id: str, owner: str, store: Any) -> tuple[Any, ...]:
    """A canonical Run whose single Attempt's provider is parked mid-flight.

    The provider sleeps on `release` — an event nothing in the product ever
    sets — so the Attempt can only settle if cancellation physically reaches
    it. `provider_exits` records the coroutine actually unwinding, which is
    what distinguishes "the work was stopped" from "the record was edited".
    """
    from services.workspace_authority import canonical_store_for_tests

    from maistro.graph import Graph, Node
    from maistro.runs import AttemptExecutionService, AttemptStatus
    from maistro.runtime import PythonExecutionRuntime

    project_store = canonical_store_for_tests().project_store
    root = await project_store.root_for_workspace(workspace_id)
    project = await project_store.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name="Parked",
    )
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project.project_id,
        name="Parked DAG",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=owner)
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
    # give the loop the ticks it needs to park the provider on `release`.
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
    return run.run_id, node_run.node_run_id, worker, release, provider_exits


async def _store_and_reader() -> tuple[Any, Any]:
    from services.workspace_authority import canonical_store_for_tests

    from maistro.runs import InMemoryRunStore
    from maistro.runs.scoped_reads import ScopedRunReader

    workspaces = canonical_store_for_tests()
    store = InMemoryRunStore(project_store=workspaces.project_store)
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    return store, reader


async def test_a_member_who_can_read_a_run_cannot_cancel_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Member B reads initiating member A's Run, yet cancellation is refused.

    The refusal is 404 — word-for-word the unknown-id answer — and it happens
    before any Run/NodeRun/Attempt transition or provider signal: the parked
    provider never unwinds, the durable fence is never attempted, and A's
    work keeps running exactly as it was.
    """
    from routes.dag_runs import cancel_run as cancel_route
    from routes.dag_runs import get_run as get_run_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import AttemptStatus, RunStatus

    view = await _workspace("Cancel Auth", _INITIATOR)
    await _grant_member(view.id, _PEER, "member")
    store, reader = await _store_and_reader()
    _engine_at(monkeypatch, store, reader)
    run_id, node_run_id, worker, release, provider_exits = await _parked_run(
        view.id, _INITIATOR, store
    )
    transitions = _transition_spy(store, monkeypatch)
    await get_dag_run_store().start_run(
        run_id="auth-member-row",
        user_id=_INITIATOR,
        workspace_id=view.id,
        canonical_run_id=run_id,
    )

    # B may read the Run: Workspace membership admits reads (#1152).
    detail = await get_run_route("auth-member-row", _ScopedRequest(_PEER))
    assert detail["canonical_run_id"] == run_id
    assert detail["status"] != "cancelled"

    # ...but a lifecycle mutation is not a read: refused with the seam's one
    # no-enumeration 404, identical to an id that never existed.
    with pytest.raises(HTTPException) as refused:
        await cancel_route("auth-member-row", _ScopedRequest(_PEER))
    assert refused.value.status_code == 404
    assert refused.value.detail == "run not found"
    with pytest.raises(HTTPException) as unknown:
        await cancel_route("auth-never-was", _ScopedRequest(_PEER))
    assert unknown.value.status_code == refused.value.status_code
    assert unknown.value.detail == refused.value.detail

    # The denial preceded the mutation: no durable fence attempted, no
    # provider unwound, the worker still parked mid-flight.
    assert transitions == []
    assert provider_exits == []
    assert not worker.done()
    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is not RunStatus.CANCELLED
    node_runs = await store.list_node_runs(run_id)
    assert node_runs and all(nr.status is not RunStatus.CANCELLED for nr in node_runs)
    attempts = await store.list_attempts(node_run_id)
    assert attempts and attempts[-1].status is AttemptStatus.RUNNING

    # Cleanup: let the parked work settle on its own terms.
    release.set()
    await worker


async def test_the_initiator_and_an_administrator_cancel_while_the_peer_cannot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A (initiator) cancels through the projection id, C (Workspace admin,
    never initiated) through the direct canonical id — and B is refused at
    every altitude between the two successes."""
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import RunStatus
    from maistro.workspaces.model import WorkspaceRole

    view = await _workspace("Cancel Auth Roles", _INITIATOR)
    await _grant_member(view.id, _PEER, WorkspaceRole.MEMBER)
    await _grant_member(view.id, _ADMIN, WorkspaceRole.OWNER)
    store, reader = await _store_and_reader()
    _engine_at(monkeypatch, store, reader)
    run_a, _nr_a, worker_a, release_a, exits_a = await _parked_run(view.id, _INITIATOR, store)
    run_b, _nr_b, worker_b, release_b, exits_b = await _parked_run(view.id, _INITIATOR, store)
    dag = get_dag_run_store()
    await dag.start_run(
        run_id="auth-row-a", user_id=_INITIATOR, workspace_id=view.id, canonical_run_id=run_a
    )
    # run_b records no projection row: the direct canonical id must behave
    # identically to a valid projection id.

    # Peer refused first — before any success below can be attributed to luck.
    with pytest.raises(HTTPException) as refused:
        await cancel_route("auth-row-a", _ScopedRequest(_PEER))
    assert refused.value.status_code == 404
    assert exits_a == [] and exits_b == []
    peer_run = await store.get_run(run_a)
    assert peer_run is not None and peer_run.status is not RunStatus.CANCELLED

    # The initiating principal cancels through the projection id.
    response = await cancel_route("auth-row-a", _ScopedRequest(_INITIATOR))
    assert response["run_id"] == run_a
    assert response["status"] == "cancelled"
    assert response["cancelled"] is True
    assert response["stop_confirmed"] is True  # the owner settled in-process (#1242)
    assert response["disposition"] == "stop_confirmed"
    with pytest.raises(asyncio.CancelledError):
        await worker_a
    assert exits_a == ["provider-stopped"]
    cancelled_a = await store.get_run(run_a)
    assert cancelled_a is not None and cancelled_a.status is RunStatus.CANCELLED

    # The Workspace administrator — who never initiated — cancels through the
    # direct canonical id: same gate, same physical outcome, no projection row.
    response = await cancel_route(run_b, _ScopedRequest(_ADMIN))
    assert response["run_id"] == run_b
    assert response["status"] == "cancelled"
    assert response["cancelled"] is True
    assert response["stop_confirmed"] is True
    assert response["disposition"] == "stop_confirmed"
    with pytest.raises(asyncio.CancelledError):
        await worker_b
    assert exits_b == ["provider-stopped"]
    cancelled_b = await store.get_run(run_b)
    assert cancelled_b is not None and cancelled_b.status is RunStatus.CANCELLED
    assert release_a.is_set() is False and release_b.is_set() is False


async def test_a_projection_row_cannot_delegate_cancellation_across_workspaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row visible in Workspace X linked to a live Run in Workspace Y lets
    neither an X-only caller nor even the Run's own initiator cancel through
    the row; the initiator's direct canonical id still works.

    The read overlay already treats a cross-Workspace canonical link as not
    this row's lifecycle truth (`_overlay`); the write side follows the same
    attribution rule, so projection linkage cannot authorize a different
    canonical Run than the row's own Workspace files.
    """
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import RunStatus
    from maistro.workspaces.model import WorkspaceRole

    row_ws = await _workspace("Cancel Row Workspace", _X_OWNER)
    run_ws = await _workspace("Cancel Run Workspace", _Y_OWNER)
    await _grant_member(row_ws.id, _Y_OWNER, WorkspaceRole.MEMBER)
    store, reader = await _store_and_reader()
    _engine_at(monkeypatch, store, reader)
    run_y, _nr_y, worker_y, release_y, exits_y = await _parked_run(run_ws.id, _Y_OWNER, store)
    transitions = _transition_spy(store, monkeypatch)
    await get_dag_run_store().start_run(
        run_id="auth-cross-row", user_id=_X_OWNER, workspace_id=row_ws.id, canonical_run_id=run_y
    )

    # The X-only caller reads the row (it lives in their Workspace) but holds
    # no authority over the Run filed in Y: refused, nothing mutated.
    with pytest.raises(HTTPException) as x_refused:
        await cancel_route("auth-cross-row", _ScopedRequest(_X_OWNER))
    assert x_refused.value.status_code == 404
    assert transitions == [] and exits_y == []

    # Even the Run's own initiator — a member of both Workspaces, so they can
    # read the row and clear the mutation gate — cannot cancel Y's Run
    # through X's row: the cross-link is not the row's lifecycle truth.
    with pytest.raises(HTTPException) as y_refused:
        await cancel_route("auth-cross-row", _ScopedRequest(_Y_OWNER))
    assert y_refused.value.status_code == 404
    assert transitions == [] and exits_y == []
    run_after = await store.get_run(run_y)
    assert run_after is not None and run_after.status is not RunStatus.CANCELLED

    # The same initiator's DIRECT canonical id is the honest path and works.
    response = await cancel_route(run_y, _ScopedRequest(_Y_OWNER))
    assert response["run_id"] == run_y
    assert response["status"] == "cancelled"
    assert response["cancelled"] is True
    assert response["stop_confirmed"] is True
    assert response["disposition"] == "stop_confirmed"
    with pytest.raises(asyncio.CancelledError):
        await worker_y
    assert exits_y == ["provider-stopped"]
    cancelled = await store.get_run(run_y)
    assert cancelled is not None and cancelled.status is RunStatus.CANCELLED
    assert release_y.is_set() is False


async def test_an_outsider_and_an_unknown_id_get_the_same_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A principal with no membership is refused exactly like a missing id,
    directly against the canonical Run's own id — no disclosure, no mutation."""
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    from maistro.runs import RunStatus

    view = await _workspace("Cancel Outsider", _INITIATOR)
    store, reader = await _store_and_reader()
    _engine_at(monkeypatch, store, reader)
    run_id, _nr, worker, release, exits = await _parked_run(view.id, _INITIATOR, store)
    transitions = _transition_spy(store, monkeypatch)
    await get_dag_run_store().start_run(
        run_id="auth-outsider-row",
        user_id=_INITIATOR,
        workspace_id=view.id,
        canonical_run_id=run_id,
    )

    with pytest.raises(HTTPException) as outsider:
        await cancel_route(run_id, _ScopedRequest(_OUTSIDER))
    assert outsider.value.status_code == 404
    assert outsider.value.detail == "run not found"
    with pytest.raises(HTTPException) as unknown:
        await cancel_route("auth-never-was", _ScopedRequest(_OUTSIDER))
    assert unknown.value.status_code == outsider.value.status_code
    assert unknown.value.detail == outsider.value.detail

    assert transitions == [] and exits == []
    assert not worker.done()
    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is not RunStatus.CANCELLED

    release.set()
    await worker


async def test_an_unstarted_engine_refuses_the_cancel_with_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No engine was ever published: the cancel seam answers 503, not 500.

    `get_engine()` raises RuntimeError when the process lifespan never started
    the engine, which is a real deployment state (boot failure, mid-restart).
    The route must translate that seam refusal into the documented
    "canonical execution spine unavailable" 504-alike — the same answer the
    missing run store gets (pinned by test_dag_run_cancel_route.py) — raised
    before any canonical target is resolved or any boundary is built, so a
    boot failure can never be mistaken for a cancellation attempt.
    """
    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_store import get_dag_run_store

    view = await _workspace("Cancel Auth No Engine", _INITIATOR)
    # The projection row is visible (read seam), so the refusal below is the
    # spine seam's, not the read seam's 404: inspection degrades gracefully
    # to the projection row when the engine is absent.
    await get_dag_run_store().start_run(
        run_id="auth-no-engine",
        user_id=_INITIATOR,
        workspace_id=view.id,
        canonical_run_id="auth-canonical-never",
    )
    monkeypatch.setattr(engine_mod, "_singleton", None)

    with pytest.raises(HTTPException) as refused:
        await cancel_route("auth-no-engine", _ScopedRequest(_INITIATOR))
    assert refused.value.status_code == 503
    assert refused.value.detail == "canonical execution spine unavailable"


async def test_a_revoked_member_is_refused_like_an_absent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Membership revoked between read and cancel: the mutation gate re-checks
    the live membership, so the refusal is the one 404 — indistinguishable
    from an id that never existed — and nothing mutates (#2466: "revoked ...
    indistinguishable").

    The read seam authorized the row once; cancellation is authorized again,
    separately, over the Workspace store's live membership at mutation time —
    so a grant that expired between the two decisions cannot ride the earlier
    answer through.
    """
    from routes.dag_runs import cancel_run as cancel_route
    from routes.dag_runs import get_run as get_run_route
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import canonical_store_for_tests

    from maistro.runs import AttemptStatus, RunStatus

    view = await _workspace("Cancel Auth Revoked", _INITIATOR)
    await _grant_member(view.id, _PEER, "member")
    store, reader = await _store_and_reader()
    _engine_at(monkeypatch, store, reader)
    run_id, node_run_id, worker, release, provider_exits = await _parked_run(
        view.id, _INITIATOR, store
    )
    transitions = _transition_spy(store, monkeypatch)
    await get_dag_run_store().start_run(
        run_id="auth-revoked-row",
        user_id=_INITIATOR,
        workspace_id=view.id,
        canonical_run_id=run_id,
    )

    # Before revocation the peer's read is admitted (#1152 membership).
    detail = await get_run_route("auth-revoked-row", _ScopedRequest(_PEER))
    assert detail["canonical_run_id"] == run_id

    await canonical_store_for_tests().remove_membership(
        view.id, user_id=_PEER, principal_id=_INITIATOR
    )

    with pytest.raises(HTTPException) as refused:
        await cancel_route("auth-revoked-row", _ScopedRequest(_PEER))
    assert refused.value.status_code == 404
    assert refused.value.detail == "run not found"
    with pytest.raises(HTTPException) as unknown:
        await cancel_route("auth-never-was", _ScopedRequest(_PEER))
    assert unknown.value.status_code == refused.value.status_code
    assert unknown.value.detail == refused.value.detail

    assert transitions == [] and provider_exits == []
    assert not worker.done()
    run_after = await store.get_run(run_id)
    assert run_after is not None and run_after.status is not RunStatus.CANCELLED
    attempts = await store.list_attempts(node_run_id)
    assert attempts and attempts[-1].status is AttemptStatus.RUNNING

    release.set()
    await worker
