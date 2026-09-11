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
not the write path that records scope — except where the write path IS the
thing under test: the canonical→projection mapping tests below pin that the
projection row is born carrying the canonical Run's Workspace/Project scope
(`canonical_dag_runner._project`, the run route's `_record_run_projection`,
the chat workflow tool's pre-execution `start_run`), and the revocation test
pins that visibility tracks the canonical membership grant, not a snapshot
taken at first read. The eval-judge verdict read side — detail and list —
is covered here too: it reads the same runs through the same door.

The in-scope SSE happy path is asserted at the handler level (the
test_design_scope.py fabricated-Request style): starlette's TestClient
buffers a response until its app completes, and this stream is deliberately
infinite (keepalives), so the transport can never see it finish.
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


@pytest.fixture(autouse=True)
def _wipe_verdicts():
    """Verdicts outlive runs in the persistence half, and this suite records
    some (the eval-judge read-side tests): isolate them per test so a verdict
    recorded for one test's run id can never answer another test's."""
    import stores

    for key in list(stores.eval_verdicts.keys()):
        stores.eval_verdicts.pop(key)
    yield
    for key in list(stores.eval_verdicts.keys()):
        stores.eval_verdicts.pop(key)


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
    [
        "/v1/dag-runs",
        "/v1/dag-runs/r-theirs",
        "/v1/dag-runs/r-theirs/events",
        "/v1/eval-judge",
        "/v1/eval-judge/r-theirs",
    ],
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


def test_dag_run_handlers_fail_closed_without_a_principal() -> None:
    """The 401s pinned above are served by AuthMiddleware; this pins the
    handlers' OWN refusal of a principal-less request (#1174). Through the
    app that arc is unreachable — middleware always sets `state.user` on
    /v1/ — so it is driven at handler level (the fabricated-Request style
    this suite already uses for the SSE half): if a request without a
    principal ever reaches a route — middleware misconfigured, the router
    mounted outside /v1/ — it must raise 401 rather than fall through
    `getattr(...) or {}` into a scope resolution for the empty principal.
    The run below EXISTS, so the 401 also proves the refusal happens before
    any store read, not merely alongside one."""
    from routes import dag_runs

    _seed_run("r-anon", workspace_id="ws-exists")

    request = SimpleNamespace(state=SimpleNamespace())  # no `user` attribute
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(dag_runs.list_runs(request))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Authentication required"


def test_eval_judge_handlers_fail_closed_without_a_principal() -> None:
    """Same fail-closed refusal, eval-judge door: the by-id verdict read
    names its principal before it authorizes the run, so a request without
    one is a 401 — never a verdict, and never a scoped existence answer
    computed for a principal nobody authenticated (#1174)."""
    from routes import eval_judge as eval_judge_routes

    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(eval_judge_routes.read_verdict("r-anon", request))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Authentication required"


# ─── fail-closed on scopeless rows ───────────────────────────────────────────


def test_a_row_written_without_scope_is_visible_to_no_one(authed_client: Any) -> None:
    """A projection row that names no Workspace proves nothing about where it
    executed — it is visible to no one, fail-closed, not even to the principal
    the row itself records (#1174; #1036's migration owns re-scoping)."""
    _seed_run("r-scopeless", user_id=_AUTHED_USER_ID)

    listed = {row["id"] for row in authed_client.get("/v1/dag-runs").json()}
    assert "r-scopeless" not in listed
    assert authed_client.get("/v1/dag-runs/r-scopeless").status_code == 404


# ── eval-judge read side over the same door ──────────────────────────────


def test_eval_judge_verdict_read_refuses_an_out_of_scope_run_like_a_missing_one(
    authed_client: Any, admin_client: Any
) -> None:
    """A verdict recorded for a run outside the caller's universe is neither
    served nor hinted at: the read authorizes the RUN first, so the answer is
    byte-identical to the one a missing run gets (#1174)."""
    theirs = _workspace(admin_client, "Admin Verdicts")
    _seed_run("r-theirs", workspace_id=theirs)

    from services.eval_judge import _persist

    _persist(
        SimpleNamespace(run_id="r-theirs"),
        {"score": 99, "rationale": "SECRET RUN CONTENT", "status": "ok"},
    )

    refused = authed_client.get("/v1/eval-judge/r-theirs")
    missing = authed_client.get("/v1/eval-judge/never-existed")
    assert refused.status_code == 404
    assert refused.json() == missing.json() == {"detail": "run not found"}
    assert "SECRET RUN CONTENT" not in refused.text


def test_eval_judge_serves_a_verdict_inside_the_callers_workspace(
    authed_client: Any,
) -> None:
    ws = _workspace(authed_client, "Mine")
    _seed_run("r-mine", workspace_id=ws)

    from services.eval_judge import _persist

    _persist(
        SimpleNamespace(run_id="r-mine"),
        {"score": 77, "rationale": "solid", "status": "ok"},
    )

    r = authed_client.get("/v1/eval-judge/r-mine")
    assert r.status_code == 200
    assert r.json()["rationale"] == "solid"


def test_verdict_missing_answer_is_only_reachable_in_scope(authed_client: Any) -> None:
    """ "No verdict for run_id" is a statement about a run the caller can
    already inspect — it must stay unreachable for out-of-scope ids, which
    get the non-existence answer one hop earlier."""
    ws = _workspace(authed_client, "Mine")
    _seed_run("r-mine", workspace_id=ws)

    r = authed_client.get("/v1/eval-judge/r-mine")
    assert r.status_code == 404
    assert r.json() == {"detail": "no verdict for run_id"}


def test_eval_judge_list_hides_out_of_scope_verdicts(authed_client: Any, admin_client: Any) -> None:
    ws = _workspace(admin_client, "Admin Verdicts")
    mine = _workspace(authed_client, "Mine")
    _seed_run("r-theirs", workspace_id=ws)
    _seed_run("r-mine", workspace_id=mine)

    from services.eval_judge import _persist

    _persist(SimpleNamespace(run_id="r-theirs"), {"score": 1, "status": "ok"})
    _persist(SimpleNamespace(run_id="r-mine"), {"score": 2, "status": "ok"})

    listed = {row["run_id"] for row in authed_client.get("/v1/eval-judge").json()}
    assert "r-theirs" not in listed
    assert "r-mine" in listed


# ── canonical → projection scope mapping (the write path) ─────────────


def test_canonical_projection_mirrors_run_scope_verbatim() -> None:
    """`_project` copies the scope fields straight off the canonical Run
    record — run_id, workspace_id, project_id — so the projection writers
    never re-derive them (#1174)."""
    from services.canonical_dag_runner import _project

    from maistro.graph.durable_runs import RunStatus

    record = SimpleNamespace(
        run_id="r-canon",
        run=SimpleNamespace(
            status=RunStatus.COMPLETED,
            error=None,
            workspace_id="ws-canonical",
            project_id="proj-canonical",
        ),
        node_runs=[],
        graph_state=SimpleNamespace(cycle=1, blackboard_snapshot={}),
    )

    projected = _project(record, {})
    assert projected["run_id"] == "r-canon"
    assert projected["workspace_id"] == "ws-canonical"
    assert projected["project_id"] == "proj-canonical"


def test_run_route_projection_is_born_with_canonical_scope_and_enforced(
    authed_client: Any, admin_client: Any
) -> None:
    """The run route's `_record_run_projection` copies the canonical result's
    scope into the projection row it opens, so the row inspection later
    authorizes at is the scope the Run was admitted into — exercised end to
    end here: the row carries the scope, the owning principal reads it, and a
    foreign principal gets the non-existence answer."""
    import asyncio

    from routes.dags import _record_run_projection
    from services.dag_run_store import get_dag_run_store

    ws = _workspace(authed_client, "Mine")
    asyncio.run(
        _record_run_projection(
            dag_id="daily-status",
            user_id=_AUTHED_USER_ID,
            result={
                "run_id": "r-canon",
                "status": "completed",
                "workspace_id": ws,
                "project_id": "proj-root",
                "node_results": {"n1": {"success": True, "role": "worker", "response": "ok"}},
            },
        )
    )

    row = get_dag_run_store().get_run("r-canon")
    assert row is not None
    assert row["workspace_id"] == ws
    assert row["project_id"] == "proj-root"
    # The projection mints no second execution identity: the canonical Run id
    # IS the projection key.
    assert row["canonical_run_id"] == "r-canon"

    assert authed_client.get("/v1/dag-runs/r-canon").status_code == 200
    refused = admin_client.get("/v1/dag-runs/r-canon")
    assert refused.status_code == 404
    assert refused.json() == {"detail": "run not found"}


def test_chat_workflow_tool_opens_the_projection_with_resolved_scope(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat workflow tool opens the projection row BEFORE executing, so
    it must already carry the scope the execution will resolve — via the same
    `resolve_execution_scope` resolver `execute_dag` uses, never a second
    mapping (#1174)."""
    import asyncio

    import services.eval_judge as eval_judge_service
    import services.graph_runner as graph_runner
    import stores
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store

    ws = _workspace(authed_client, "Chat Scope")
    dag_id = "dag-chat-scope"
    stores.dags[dag_id] = {
        "id": dag_id,
        "name": "Chat Scope",
        "description": "",
        "workspace_id": ws,
        "project_id": "proj-chat",
    }

    async def _fake_execute_dag(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        return {"status": "completed", "run_id": "ignored", "node_results": {}}

    async def _fake_score_run(run_record: Any, **kw: Any) -> dict:
        return {"score": 50}

    monkeypatch.setattr(graph_runner, "execute_dag", _fake_execute_dag)
    monkeypatch.setattr(eval_judge_service, "score_run", _fake_score_run)

    out = asyncio.run(
        _tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None)
    )
    assert out.get("run_id"), out  # surfaces the tool's error text on failure

    row = get_dag_run_store().get_run(str(out["run_id"]))
    assert row is not None
    assert row["workspace_id"] == ws
    assert row["project_id"]
    assert row["project_id"] != "proj-chat"


# ── authorization tracks the canonical grant ──────────────────────────


def test_revoking_workspace_membership_revokes_run_visibility(
    authed_client: Any, admin_client: Any
) -> None:
    """Visibility is re-derived from the canonical Workspace store on every
    read (#1174) — never cached at first contact. While the caller is a
    member, list/detail answer; the moment the owner revokes the membership,
    every door answers exactly as it would for a run that never existed."""
    ws = _workspace(admin_client, "Revocable")
    added = admin_client.post(
        f"/v1/workspaces/{ws}/members",
        json={"user_id": _AUTHED_USER_ID, "role": "viewer"},
    )
    assert added.status_code == 200, added.text
    _seed_run("r-shared", workspace_id=ws)

    # While the grant stands, the run is listed and readable.
    assert "r-shared" in {row["id"] for row in authed_client.get("/v1/dag-runs").json()}
    assert authed_client.get("/v1/dag-runs/r-shared").status_code == 200

    revoked = admin_client.delete(f"/v1/workspaces/{ws}/members/{_AUTHED_USER_ID}")
    assert revoked.status_code == 200, revoked.text

    listed = {row["id"] for row in authed_client.get("/v1/dag-runs").json()}
    assert "r-shared" not in listed
    refused = authed_client.get("/v1/dag-runs/r-shared")
    assert refused.status_code == 404
    assert refused.json() == {"detail": "run not found"}
    sse = authed_client.get("/v1/dag-runs/r-shared/events")
    assert sse.status_code == 404
    assert sse.json() == {"detail": "run not found"}
