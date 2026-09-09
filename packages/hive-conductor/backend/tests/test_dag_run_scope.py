"""DAG-Run reads are scoped to the caller's canonical Workspace universe (#1174).

GET /v1/dag-runs (list), GET /v1/dag-runs/{id} (detail) and
GET /v1/dag-runs/{id}/events (SSE) used to answer whoever held a run id:
`DagRunStore` is projection storage (#697) and never asked who was asking.
Every response now goes through `services/dag_run_inspection`, which
authorizes at the caller's canonical Workspace boundary — the same authority
`routes/agents.py` answers through (`services.workspace_authority`, #37).

The refusals are deliberately 404-shaped: "exists beyond your boundary" and
"does not exist" are indistinguishable by protocol contract, mirroring the
design routes' scoped 404 (#326). Authentication alone is refused with 401 by
AuthMiddleware before any handler — and therefore before any existence
signal — and the unauthenticated cases pin that too.

Run rows here are seeded straight into `dag_run_store` (the established
pattern, cf. test_eval_judge.py): the thing under test is the scope decision,
not the write path that records scope. The in-scope SSE happy path is asserted
at the handler level (the test_design_scope.py fabricated-Request style):
starlette's TestClient buffers a response until its app completes, and this
stream is deliberately infinite (keepalives), so the transport can never see
it finish.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("boundary")]

_AUTHED_USER_ID = "user"  # the session conftest seeds


class _ScopedRequest:
    """Just what the dag-runs handlers read off a request: `state.user` and
    `is_disconnected()` (the SSE generator's cancel check)."""

    def __init__(self, user_id: str) -> None:
        self.state = SimpleNamespace(user={"id": user_id, "username": user_id})

    async def is_disconnected(self) -> bool:  # pragma: no cover - cancel check
        return False


async def _seed_run_async(run_id: str, *, workspace_id: str = "", user_id: str = "") -> None:
    """Put one run row into the projection, carrying (or lacking) scope."""
    from services.dag_run_store import get_dag_run_store

    store = get_dag_run_store()
    await store.start_run(run_id=run_id, user_id=user_id, workspace_id=workspace_id)
    await store.append_event(
        run_id,
        event_type="pm_node_started",
        role="intake",
        capability="create_initiative",
    )


def _seed_run(run_id: str, *, workspace_id: str = "", user_id: str = "") -> None:
    # asyncio.run() uses a fresh loop — robust regardless of prior async tests.
    asyncio.run(_seed_run_async(run_id, workspace_id=workspace_id, user_id=user_id))


def _workspace(client: Any, name: str) -> str:
    """A Workspace the client's principal owns (the caller becomes owner)."""
    r = client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ─── list ────────────────────────────────────────────────────────────────────


def test_list_shows_runs_inside_the_callers_workspace(authed_client: Any) -> None:
    ws = _workspace(authed_client, "Mine")
    _seed_run("r-mine", workspace_id=ws)

    listed = {row["id"] for row in authed_client.get("/v1/dag-runs").json()}
    assert "r-mine" in listed


def test_list_hides_runs_outside_the_callers_workspace(
    authed_client: Any, admin_client: Any
) -> None:
    theirs = _workspace(admin_client, "Admin Only")
    _seed_run("r-theirs", workspace_id=theirs)

    mine = _workspace(authed_client, "Mine")
    _seed_run("r-mine", workspace_id=mine)

    from services.workspace_authority import list_views_for_user

    rows = authed_client.get("/v1/dag-runs").json()
    allowed = {view.id for view in asyncio.run(list_views_for_user(_AUTHED_USER_ID))}

    # A foreign run is never listed...
    assert "r-theirs" not in {row["id"] for row in rows}
    # ...the caller's own run is...
    assert "r-mine" in {row["id"] for row in rows}
    # ...and the stronger invariant holds for every row, whatever else this
    # process's projection buffer happens to carry: a listed row's Workspace
    # is always one of the caller's own.
    assert all(row["workspace_id"] in allowed for row in rows)


# ─── detail ──────────────────────────────────────────────────────────────────


def test_detail_serves_a_run_inside_the_callers_workspace(authed_client: Any) -> None:
    ws = _workspace(authed_client, "Mine")
    _seed_run("r-mine", workspace_id=ws)

    r = authed_client.get("/v1/dag-runs/r-mine")
    assert r.status_code == 200
    assert r.json()["id"] == "r-mine"
    # The full event log a scoped reader is entitled to.
    assert any(ev["event_type"] == "pm_node_started" for ev in r.json()["events"])


def test_detail_refuses_an_out_of_scope_run_like_a_missing_one(
    authed_client: Any, admin_client: Any
) -> None:
    theirs = _workspace(admin_client, "Admin Only")
    _seed_run("r-theirs", workspace_id=theirs)

    refused = authed_client.get("/v1/dag-runs/r-theirs")
    missing = authed_client.get("/v1/dag-runs/never-existed")
    assert refused.status_code == 404
    assert refused.json() == missing.json() == {"detail": "run not found"}


# ─── SSE ─────────────────────────────────────────────────────────────────────


def test_sse_refuses_an_out_of_scope_run_before_any_stream(
    authed_client: Any, admin_client: Any
) -> None:
    theirs = _workspace(admin_client, "Admin Only")
    _seed_run("r-theirs", workspace_id=theirs)

    r = authed_client.get("/v1/dag-runs/r-theirs/events")
    assert r.status_code == 404
    assert r.json() == {"detail": "run not found"}
    assert "text/event-stream" not in r.headers.get("content-type", "")


async def test_sse_streams_and_replays_inside_the_callers_workspace(
    authed_client: Any,
) -> None:
    """In scope, the route opens a live SSE stream that replays the run's
    buffered events — asserted at the handler level (see module docstring for
    why the HTTP transport cannot carry an infinite stream in tests)."""
    ws = _workspace(authed_client, "Mine")
    await _seed_run_async("r-mine", workspace_id=ws)

    from routes.dag_runs import stream_run_events

    response = await stream_run_events("r-mine", _ScopedRequest(_AUTHED_USER_ID))
    assert response.media_type == "text/event-stream"

    # Deterministic yields: the connected preamble, then the one event the
    # seed buffered. Two reads, then close — never the keepalive loop.
    preamble = await anext(response.body_iterator)
    event_frame = await anext(response.body_iterator)
    await response.body_iterator.aclose()
    assert ": connected" in preamble
    assert "pm_node_started" in event_frame


# ─── authentication vs authorization ─────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/v1/dag-runs", "/v1/dag-runs/r-theirs", "/v1/dag-runs/r-theirs/events"],
)
def test_unauthenticated_reads_are_refused_before_any_existence_signal(
    path: str, admin_client: Any
) -> None:
    """401 without a session — even for a run id that exists. Authentication
    happens in the middleware; authorization (scope) happens in the route;
    neither leaks a existence signal without the other."""
    theirs = _workspace(admin_client, "Admin Only")
    _seed_run("r-theirs", workspace_id=theirs)

    from fastapi.testclient import TestClient
    from main import app

    anonymous = TestClient(app)
    r = anonymous.get(path)
    assert r.status_code == 401
    assert r.json() == {"detail": "Authentication required"}


# ─── fail-closed on scopeless rows ───────────────────────────────────────────


def test_a_row_written_without_scope_is_visible_to_no_one(authed_client: Any) -> None:
    """A projection row that names no Workspace proves nothing about where it
    executed — it is visible to no one, fail-closed, not even to the principal
    the row itself records (#1174; #1036's migration owns re-scoping)."""
    _seed_run("r-scopeless", user_id=_AUTHED_USER_ID)

    listed = {row["id"] for row in authed_client.get("/v1/dag-runs").json()}
    assert "r-scopeless" not in listed
    assert authed_client.get("/v1/dag-runs/r-scopeless").status_code == 404
