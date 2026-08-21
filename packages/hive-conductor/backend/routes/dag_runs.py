"""DAG-run live state API — list, detail, SSE event stream.

Day 6 v0 deliverable. Frontend DagBuilder.tsx (or a sibling RunViewer
page) consumes:
  GET /v1/dag-runs               — list recent runs + summary node states
  GET /v1/dag-runs/{id}          — single run with full event log
  GET /v1/dag-runs/{id}/events   — SSE stream of live events

SSE is the live-update path. Frontend opens the stream when the user
clicks "View live run" on the Fleet pulse page; updates the react-flow
node states in real time.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from services.dag_run_store import get_dag_run_store

router = APIRouter(tags=["dag-runs"])


@router.get("")
def list_runs(limit: int = 25) -> list[dict[str, Any]]:
    store = get_dag_run_store()
    return store.list_runs(limit=max(1, min(limit, 100)))


@router.get("/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    store = get_dag_run_store()
    detail = store.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="run not found")
    return detail


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream of pm_node_* events for one run. Cancels when the client
    disconnects. Replays any already-buffered events first so late
    subscribers see the full run state."""
    store = get_dag_run_store()
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")

    q = store.subscribe(run_id)

    async def event_gen():
        # Helpful preamble + keepalive comment so corp proxies don't kill idle SSE.
        yield ": connected\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keepalive\n\n"  # SSE comment line; ignored by clients
                    continue
                payload = {
                    "event_type": ev.event_type,
                    "role": ev.role,
                    "capability": ev.capability,
                    "payload": ev.payload,
                    "timestamp": ev.timestamp,
                }
                yield f"event: {ev.event_type}\ndata: {json.dumps(payload)}\n\n"
        finally:
            store.unsubscribe(run_id, q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering for live SSE
        },
    )
