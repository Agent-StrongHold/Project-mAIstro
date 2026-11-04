"""One request correlation identity across the real Hive->maistro-server boundary (#1063).

Closes the two acceptance items the reopened issue still tracks. Everything
this file drives is production code except the socket pair: Hive's real
`main:app` (RequestIDMiddleware -> auth -> missions route -> EngineService ->
`MaistroServerTaskBackend`) is handed an httpx client whose transport is the
real maistro-server ASGI app (RequestIDMiddleware -> auth -> /tasks route ->
TaskQueue -> `TaskRunAdmitter` -> durable SQLite Run spine + idempotency
claims). httpx's `ASGITransport` is the one substitution — the HTTP client
edge, not any service behind it — which is the boundary-level integration
this suite can run without two live processes and a compose stack; the PR
body says so explicitly rather than claiming a live two-process E2E.

What that proves, as one chain: the id `RequestIDMiddleware` adopted for the
Hive request is (a) echoed to the user in Hive's response, (b) forwarded
unsigned by the task backend, (c) adopted — not replaced — by maistro-server's
own `RequestIDMiddleware` for the service-hop request, and (d) recorded by
`TaskRunAdmitter` on the canonical Run's provenance. One id, four places.

Suite conventions this file follows: `TestClient(app)` is used *without* the
lifespan context manager (see `test_production_workspace_scope.py`), so the
app runs on the conftest-seeded in-memory stores rather than re-loading the
operator's real `~/.conductor` state database.
"""

from __future__ import annotations

import importlib
import pathlib
import re
import sys
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite
import httpx
import pytest
from fastapi.testclient import TestClient

from maistro.observability.middleware import REQUEST_ID_HEADER
from maistro.runs.store_boundary import RunStoreBoundary
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.idempotency import SqliteTaskIdempotencyStore
from maistro.tasks.models import TaskCreate
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole
from maistro_server.api.runs import configure_run_boundary, configure_run_store
from maistro_server.main import app as server_app

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

DELEGATION_KEY = "test-only-task-delegation-key"
CORRELATION_ID = "caller-supplied-req-1063"
#: The shape `RequestIDMiddleware` mints when no valid client id arrives.
_SERVER_MINTED = re.compile(r"[0-9a-f]{12}")


@pytest.fixture
async def server_spine(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Any]]:
    """maistro-server wired as a durable deployment is: SQLite spine + claims.

    Same shape as `test_task_workspace_scope.durable_spine`, plus the
    idempotency claim store (#1176) a durable deployment wires, so a
    transport replay of one submission reconciles to the Run it already
    admitted instead of minting a second one. The service credential and
    delegation key are pinned the same way that test pins them: the backend's
    signed delegation envelope is only accepted against an authenticated
    service principal, so the server must actually authenticate "conductor".
    No Workspace-scope proof key: this file submits unscoped (default
    Workspace), because #1063 is correlation and a Workspace-scoped admission
    would pull in the #234 scope machinery this file does not claim to test.
    """
    from maistro.config.settings import get_settings

    previous_queue = queue_module._queue
    queue_module._queue = None
    monkeypatch.setenv("API_KEYS", '["conductor:service-secret"]')
    monkeypatch.setenv("TASK_DELEGATION_KEY", DELEGATION_KEY)
    get_settings.cache_clear()
    conn = await aiosqlite.connect(tmp_path / "spine.db")
    (
        scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(conn, workspace_id="default")
    claims = SqliteTaskIdempotencyStore(conn)
    await claims.ensure_schema()
    workspaces = InMemoryWorkspaceStore(project_store=scope_store)
    await workspaces.create(creator_user_id="dev", name="default", workspace_id="default")
    for member in ("user", "admin"):
        await workspaces.set_membership("default", user_id=member, role=WorkspaceRole.MEMBER)
    queue_module.configure_task_queue(admitter=admitter, idempotency_store=claims)
    configure_run_store(run_store)
    configure_run_boundary(RunStoreBoundary(run_store, workspaces, scope_store))
    try:
        yield scope_store, run_store
    finally:
        configure_run_store(None)
        configure_run_boundary(None)
        queue_module._queue = previous_queue
        await conn.close()
        get_settings.cache_clear()


@pytest.fixture
def hive_engine(monkeypatch: pytest.MonkeyPatch, server_spine: Any) -> Iterator[Any]:
    """Hive's production engine holding the production HTTP task backend.

    The backend's httpx client is redirected onto the real server ASGI app —
    the one substitution this file makes, at the HTTP client edge — so every
    hop the issue names runs for real: middleware, auth, route, backend,
    service-hop request, server middleware, queue, admitter, Run store.
    """
    backend_module = importlib.import_module("adapters.task_backend")
    engine_module = importlib.import_module("services.engine")

    @asynccontextmanager
    async def _server_transport(*, timeout: float):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server_app),
            base_url="http://maistro-server",
            timeout=timeout,
        ) as client:
            yield client

    monkeypatch.setattr(backend_module, "shared_client", _server_transport)
    backend = backend_module.MaistroServerTaskBackend(
        base_url="http://maistro-server",
        api_key="service-secret",
        delegation_key=DELEGATION_KEY,
        service_principal="conductor",
    )
    engine = engine_module.EngineService()
    engine._backend = backend
    monkeypatch.setattr(engine_module, "_singleton", engine)
    yield engine


def _login(client: TestClient) -> None:
    """Log in through the real route, seeding the suite's user if stores are empty."""
    import stores

    if len(stores.users) == 0:
        from datetime import UTC, datetime

        now_ts = datetime.now(UTC)
        stores.users["user"] = stores.users._model_class(
            id="user",
            username="testuser",
            password_hash="$2b$12$hmpbR.C6bkLEJ4d9PYzoqOthlZNKk.WOSjXnLxHpC0Y3S6sgdYfPq",
            role="user",
            is_active=True,
            permissions=[],
            created_at=now_ts,
        )
    response = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert response.status_code == 200, response.text


async def test_one_request_id_crosses_the_boundary_onto_the_run(
    server_spine: Any, hive_engine: Any
) -> None:
    """The acceptance chain: Hive response == service hop == Run provenance.

    A regression that breaks any link fails here: `RequestIDMiddleware` not
    wired into Hive (no header echo, nothing bound for the backend to
    forward), `MaistroServerTaskBackend` dropping the header (maistro-server
    allocates an unrelated id for the hop and the Run's provenance disagrees
    with the response the user saw), or `TaskRunAdmitter` not recording it
    (provenance missing the request id entirely).
    """
    _scope_store, run_store = server_spine
    from main import app as hive_app

    hive_client = TestClient(hive_app)
    _login(hive_client)
    response = hive_client.post(
        "/v1/tasks",
        json={"name": "correlate me", "description": "one id, four places"},
        headers={REQUEST_ID_HEADER: CORRELATION_ID},
    )
    assert response.status_code == 200, response.text

    # (a) Hive's own middleware adopted the client id and echoed it back.
    assert response.headers[REQUEST_ID_HEADER] == CORRELATION_ID

    # The task the route created is visible through the same backend, and its
    # receipt carries the canonical Run the server admitted for it.
    mission = response.json()
    assert mission["id"], mission
    record = await hive_engine._backend.get_async(mission["id"], user_id="user")
    assert record is not None, "the submitted task must be visible through the backend"
    assert record.run_id, "the server must have admitted a canonical Run"

    # (b)+(c)+(d) The server adopted the *forwarded* id — its Run provenance
    # carries the Hive request's id, not a fresh allocation for the hop — and
    # the admitter recorded it beside the task's own provenance keys.
    run = await run_store.get_run(record.run_id)
    assert run is not None
    assert run.provenance.get("request_id") == CORRELATION_ID
    assert run.provenance.get("task_id") == mission["id"]
    assert run.provenance.get("admission_source") == "task_queue"


async def test_a_retried_request_keeps_the_same_logical_identity(
    server_spine: Any, hive_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance: a transport retry does not mint a new logical identity.

    The first service-hop POST dies at the transport boundary (a dropped
    connection — the server never saw a complete request, so nothing was
    admitted), and Hive's route answers 500 through its unhandled-exception
    handler with the same request id attached. The caller's HTTP retry policy
    then re-issues the *same logical request* — a new transport attempt
    carrying the same client-supplied `X-Request-ID`. Hive's middleware
    re-adopts it, the backend forwards the same bound id again, and the Run
    the retry admitted carries the one logical identity. Per-attempt
    transport ids (the fresh ids each attempt's middleware would allocate
    absent a forwarded one) never appear anywhere durable.
    """
    _scope_store, run_store = server_spine
    backend_module = importlib.import_module("adapters.task_backend")
    from main import app as hive_app

    forwarded: list[str | None] = []

    class _DropFirstTransport(httpx.AsyncBaseTransport):
        """The real server app, but the first POST loses its connection."""

        def __init__(self) -> None:
            self._inner = httpx.ASGITransport(app=server_app)
            self._posts = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/tasks":
                self._posts += 1
                forwarded.append(request.headers.get(REQUEST_ID_HEADER))
                if self._posts == 1:
                    # Transport-level failure: the connection drops before a
                    # response is produced. Whether the server saw the bytes
                    # is exactly the ambiguity a retry has to tolerate.
                    raise httpx.ConnectError("simulated connection drop")
            return await self._inner.handle_async_request(request)

    transport = _DropFirstTransport()

    @asynccontextmanager
    async def _flaky_transport(*, timeout: float):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://maistro-server", timeout=timeout
        ) as client:
            yield client

    monkeypatch.setattr(backend_module, "shared_client", _flaky_transport)

    hive_client = TestClient(hive_app, raise_server_exceptions=False)
    _login(hive_client)
    first = hive_client.post(
        "/v1/tasks",
        json={"name": "retry me", "description": "same logical request"},
        headers={REQUEST_ID_HEADER: CORRELATION_ID},
    )
    # The backend's transport failure surfaces to the route caller as Hive's
    # own 500 — and the id is still on it, which is when a caller needs it most.
    assert first.status_code == 500
    assert first.headers[REQUEST_ID_HEADER] == CORRELATION_ID

    second = hive_client.post(
        "/v1/tasks",
        json={"name": "retry me", "description": "same logical request"},
        headers={REQUEST_ID_HEADER: CORRELATION_ID},
    )
    assert second.status_code == 200, second.text

    # Both transport attempts to maistro-server carried the same logical id:
    # the header the backend forwards is the request-context id, which a
    # retry re-binds, not a per-attempt value minted at send time.
    assert forwarded == [CORRELATION_ID, CORRELATION_ID]

    mission = second.json()
    record = await hive_engine._backend.get_async(mission["id"], user_id="user")
    assert record is not None
    assert record.run_id
    run = await run_store.get_run(record.run_id)
    assert run is not None
    # One logical identity on the durable record: the Run the retry admitted
    # carries the same id the first attempt tried to carry.
    assert run.provenance.get("request_id") == CORRELATION_ID


async def test_a_transport_replay_reconciles_to_one_run_with_one_identity(
    server_spine: Any, hive_engine: Any
) -> None:
    """Acceptance: a replay does not create a second logical identity.

    The response to the first submission is lost after the server admitted
    it, so the backend re-sends the identical submission — the transport
    replay shape. The server's idempotency contract (#1176) reconciles the
    byte-identical payload under the same principal to the receipt it
    already issued, so the retry resolves to the *same* task and the *same*
    Run, and that Run's provenance carries the one request id both attempts
    forwarded. A second Run with a fresh correlation root is exactly the
    failure this acceptance rules out.
    """
    _scope_store, run_store = server_spine
    from maistro.observability.correlation import bind_execution_context

    create = TaskCreate(description="replay me: response lost, resend")
    with bind_execution_context(request_id=CORRELATION_ID):
        first = await hive_engine._backend.submit(create, user_id="user")
        retried = await hive_engine._backend.submit(create, user_id="user")

    assert first.run_id and retried.run_id
    assert retried.run_id == first.run_id, "a replay must reconcile to the admitted Run"
    assert retried.id == first.id
    run = await run_store.get_run(first.run_id)
    assert run is not None
    assert run.provenance.get("request_id") == CORRELATION_ID


async def test_background_admission_gets_a_new_correlation_root(
    server_spine: Any, hive_engine: Any
) -> None:
    """Acceptance: background/system admission mints its own correlation root.

    A submission made with no HTTP request in scope — the exact situation a
    background job or a scheduler firing finds itself in — forwards no id
    rather than inheriting some unrelated ambient request, and the server's
    own middleware allocates a fresh root for it. The Run's provenance
    carries that fresh id, never blank and never an earlier request's.
    """
    _scope_store, run_store = server_spine
    record = await hive_engine._backend.submit(
        TaskCreate(description="background sweep"), user_id="system"
    )

    assert record.run_id
    run = await run_store.get_run(record.run_id)
    assert run is not None
    recorded = run.provenance.get("request_id")
    # A fresh server-allocated root in the middleware's minted shape — not
    # blank, and not any id an earlier request in this file supplied.
    assert isinstance(recorded, str)
    assert _SERVER_MINTED.fullmatch(recorded), recorded
    assert recorded != CORRELATION_ID
