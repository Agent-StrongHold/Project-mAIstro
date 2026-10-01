"""DAG-run live state API — list, detail, SSE event stream.

Day 6 v0 deliverable. Frontend DagBuilder.tsx (or a sibling RunViewer
page) consumes:
  GET /v1/dag-runs               — list recent runs + summary node states
  GET /v1/dag-runs/{id}          — single run with full event log
  GET /v1/dag-runs/{id}/events   — SSE stream of live events

SSE is the live-update path. Frontend opens the stream when the user
clicks "View live run" on the Fleet pulse page; updates the react-flow
node states in real time.

Every response is scoped (#1174): the routes read through
`services.dag_run_inspection`, which authorizes at the caller's canonical
Workspace boundary — the same authority the workspace/agents routes use —
before any metadata, event, existence signal, or stream is served. A run
outside that boundary is indistinguishable from a run that does not exist.
Authentication happens in AuthMiddleware; it is not authorization.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from services.dag_run_inspection import can_inspect_run, list_visible_runs, visible_run_detail
from services.dag_run_store import get_dag_run_store

router = APIRouter(tags=["dag-runs"])


def _user_id(request: Request) -> str:
    """Principal for this request — set by AuthMiddleware on every /v1/ path.

    The explicit refusal mirrors routes/feedback.py: a handler that cannot
    name its principal must fail closed rather than guess, because every
    response below is scoped to that principal's Workspace universe (#1174).
    """
    user = getattr(request.state, "user", None) or {}
    uid = str(user.get("id") or user.get("username") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid


@router.get("")
async def list_runs(request: Request, limit: int = 25) -> list[dict[str, Any]]:
    uid = _user_id(request)
    return await list_visible_runs(uid, limit=max(1, min(limit, 100)))


@router.get("/retention")
def retention() -> dict[str, Any]:
    """What this deployment keeps, and whether it keeps it across a restart.

    A separate endpoint rather than a field on the list, which would change
    that response from an array to an object and break every existing reader.

    It exists because the bound was invisible: a `maxlen=100` deque behind a
    page headed "Live DAG Runs" with a "Recent runs" sidebar, discarding the
    101st run and every run at restart, with nothing anywhere saying so
    (#697, and the rule #333 set for exactly this).

    Declared before `/{run_id}`: FastAPI matches in definition order, so the
    parameterised route would otherwise swallow this path and answer
    "run not found" for it.

    Deployment-level constants, not run data: no principal is read and no
    per-run scoping applies, exactly as before (#1174 scoped the run-bearing
    routes, not this description of the store's bounds).
    """
    from services.dag_run_store import MAX_EVENTS_PER_RUN, MAX_RUNS

    store = get_dag_run_store()
    return {
        "durable": store.is_durable,
        "max_runs": MAX_RUNS,
        "max_events_per_run": MAX_EVENTS_PER_RUN,
    }


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> dict[str, Any]:
    """Cancel through the canonical Run/Attempt execution seam."""
    uid = _user_id(request)
    detail = await visible_run_detail(uid, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="run not found")

    from services.engine import get_engine

    from maistro.runs.service import RunExecutionService
    from maistro.runtime import PythonExecutionRuntime

    store = get_engine().run_store
    if store is None:
        raise HTTPException(status_code=503, detail="canonical execution spine unavailable")
    try:
        updated = await RunExecutionService(
            store=store,
            runtime=PythonExecutionRuntime(),
        ).cancel_run(str(detail.get("canonical_run_id") or run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {
        "run_id": updated.run_id,
        "status": updated.status.value,
        "cancelled": updated.status.value == "cancelled",
    }


@router.get("/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    uid = _user_id(request)
    detail = await visible_run_detail(uid, run_id)
    if detail is None:
        # Same answer for "no such run" and "not in your Workspace universe":
        # a scoped refusal must not confirm that an out-of-scope run exists.
        raise HTTPException(status_code=404, detail="run not found")
    return detail


def _resync_frame(run_id: str, last_seq: int, current_seq: int) -> str:
    """The explicit discontinuity marker (#1183).

    A full bounded subscriber queue drops events; a trimmed run buffer loses
    the oldest history. Neither may reach the client as silence: the next
    delivered event is preceded by a resync that says how many events were
    lost and where durable truth lives, so a consumer can converge on the
    canonical Run instead of believing a contiguous stream that isn't.
    """
    payload = {
        "run_id": run_id,
        "last_seq": last_seq,
        "resumed_at": current_seq,
        "missed": max(0, current_seq - last_seq - 1),
        "recover": f"GET /v1/dag-runs/{run_id}",
    }
    return f"event: pm_resync\ndata: {json.dumps(payload)}\n\n"


async def _next_authorized_event(uid: str, run_id: str, q: asyncio.Queue[Any]) -> tuple[bool, Any]:
    """One wait cycle: (stream_alive, event_or_none).

    `alive=False` ends the stream. `event=None` with `alive=True` is an idle
    tick: poll the canonical Workspace boundary even when the run is idle
    (otherwise revocation leaves an open stream authorized until the next
    event arrives) and let the caller emit its keepalive comment.
    """
    # Membership can be revoked while q.get() is waiting. Check before
    # waiting so a queued event is not exposed after the last successful
    # authorization check.
    if not await can_inspect_run(uid, run_id):
        return False, None
    try:
        ev = await asyncio.wait_for(q.get(), timeout=15.0)
    except TimeoutError:
        if not await can_inspect_run(uid, run_id):
            return False, None
        return True, None
    # Do not yield an event that was queued before membership was revoked
    # while this connection was waiting for it.
    if not await can_inspect_run(uid, run_id):
        return False, None
    return True, ev


async def _event_generator(*, uid: str, run_id: str, request: Request, store: Any):
    q: asyncio.Queue[Any] | None = None
    # Highest event seq delivered on this stream. Events carry their per-run
    # sequence number (#1183); a delivered seq that jumps past `last_seq + 1`
    # means the bounded queue dropped events, and the consumer is told.
    last_seq = 0
    try:
        # Authorization is intentionally checked again when the stream starts.
        # The response may have been created after the route's admission check
        # but before this generator is first resumed. Delay subscription until
        # this check so an abandoned response cannot leave an unauthorized
        # live queue behind.
        if not await can_inspect_run(uid, run_id):
            return
        q = store.subscribe(run_id)

        # Helpful preamble + keepalive comment so corp proxies don't kill idle
        # SSE. It contains no run data, but is emitted only while the
        # subscription is still authorized.
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            alive, ev = await _next_authorized_event(uid, run_id, q)
            if not alive:
                break
            if ev is None:
                yield ": keepalive\n\n"  # SSE comment line; ignored by clients
                continue
            if ev.seq > last_seq + 1:
                # Covers both discontinuity sources: the subscriber queue
                # overflowed while this consumer was slow, or the replayed
                # buffer begins past seq 1 because the run's bounded history
                # was trimmed before we subscribed (#1183).
                yield _resync_frame(run_id, last_seq, ev.seq)
            if ev.seq > last_seq:
                last_seq = ev.seq
            payload = {
                "event_type": ev.event_type,
                "role": ev.role,
                "capability": ev.capability,
                "payload": ev.payload,
                "timestamp": ev.timestamp,
                "seq": ev.seq,
            }
            yield f"event: {ev.event_type}\ndata: {json.dumps(payload)}\n\n"
    finally:
        if q is not None:
            store.unsubscribe(run_id, q)


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream of pm_node_* events for one run. Cancels when the client
    disconnects. Replays any already-buffered events first so late
    subscribers see the full run state."""
    uid = _user_id(request)
    # Scope authorization happens HERE, before the subscription queue exists
    # and before anything is streamed or replayed into it (#1174). An
    # out-of-scope id gets the same 404 a missing run gets.
    if not await can_inspect_run(uid, run_id):
        raise HTTPException(status_code=404, detail="run not found")

    store = get_dag_run_store()

    return StreamingResponse(
        _event_generator(uid=uid, run_id=run_id, request=request, store=store),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering for live SSE
        },
    )
