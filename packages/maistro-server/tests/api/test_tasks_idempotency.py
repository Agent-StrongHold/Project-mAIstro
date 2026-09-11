"""POST /tasks reconciles retries at the HTTP boundary (#1176).

The core tests prove the contract's mechanics; this proves the wire format —
the standard ``Idempotency-Key`` header reaches admission, a retry answers
with the original task_id and run_id, a reused key with a different payload is
a 409 rather than somebody's stale Run, and the same textual key across two
authenticated callers admits twice without either caller being able to read
the other's work.

The parity assertion matters as much as the new cases: no key at all must
behave exactly as before. The durable half of the file puts the same wire on
the SQLite claim tier, because the issue's stop condition forbids a
process-local cache: the timeout/retry, concurrent-retry, restart and
replica-handoff shapes are only real when the claims outlive the process that
made them.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from maistro.config.settings import Settings, get_settings
from maistro.runs.model import RunStatus
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.idempotency import (
    TASK_SUBMIT_ACTION,
    InMemoryTaskIdempotencyStore,
    SqliteTaskIdempotencyStore,
    admission_scope_key,
)
from maistro.tasks.queue import TaskQueue, configure_task_queue, reset_task_queue
from maistro_server.api.tasks import router as tasks_router

WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 — API contract, gated by the route


@pytest.fixture
async def wired() -> AsyncIterator[tuple[TaskQueue, object, FastAPI]]:
    """A queue on a real Run spine with the in-memory claim tier, as the app's
    lifespan would wire for a no-database deployment.

    The router resolves the queue through the process singleton, so installing
    it here is the wiring — no per-app override needed, which is also what
    keeps these requests on the exact code path production uses.
    """
    previous = queue_module._queue
    queue_module._queue = None
    (
        _scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="test-workspace")
    queue = configure_task_queue(
        admitter=admitter, idempotency_store=InMemoryTaskIdempotencyStore()
    )
    app = FastAPI()
    app.include_router(tasks_router)
    try:
        yield queue, run_store, app
    finally:
        queue_module._queue = previous


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


async def test_a_retry_with_the_same_key_reconciles(wired) -> None:
    queue, run_store, app = wired
    client = _client(app)
    body = {"description": "Add a hello endpoint", "workspace": WORKSPACE}

    first = client.post("/tasks", json=body, headers={"Idempotency-Key": "k-1"})
    retry = client.post("/tasks", json=body, headers={"Idempotency-Key": "k-1"})

    assert first.status_code == 202
    assert retry.status_code == 202
    assert retry.json()["task_id"] == first.json()["task_id"]
    assert retry.json()["run_id"] == first.json()["run_id"]
    assert retry.json()["task"]["run_id"] == retry.json()["run_id"]
    # One receipt, one Run: the retry minted neither.
    receipts, _cursor = queue.list_tasks(user_id="dev")
    assert len(receipts) == 1
    assert await run_store.get_run(first.json()["run_id"]) is not None


async def test_a_reused_key_with_a_different_payload_is_409(wired) -> None:
    _queue, run_store, app = wired
    client = _client(app)

    first = client.post(
        "/tasks",
        json={"description": "first", "workspace": WORKSPACE},
        headers={"Idempotency-Key": "k-1"},
    )
    mismatch = client.post(
        "/tasks",
        json={"description": "different work", "workspace": WORKSPACE},
        headers={"Idempotency-Key": "k-1"},
    )

    assert first.status_code == 202
    assert mismatch.status_code == 409
    assert "different request payload" in mismatch.json()["detail"]
    # And the refusal minted nothing: the original Run is still the only one.
    assert await run_store.get_run(first.json()["run_id"]) is not None


async def test_header_and_body_keys_must_agree(wired) -> None:
    _queue, _run_store, app = wired
    client = _client(app)

    agreeing = client.post(
        "/tasks",
        json={"description": "x", "workspace": WORKSPACE, "idempotency_key": "k-1"},
        headers={"Idempotency-Key": "k-1"},
    )
    conflicting = client.post(
        "/tasks",
        json={"description": "x", "workspace": WORKSPACE, "idempotency_key": "k-1"},
        headers={"Idempotency-Key": "k-2"},
    )

    assert agreeing.status_code == 202
    assert conflicting.status_code == 422
    assert "conflicting idempotency keys" in conflicting.json()["detail"]


async def test_an_oversized_key_is_422(wired) -> None:
    _queue, _run_store, app = wired
    client = _client(app)

    response = client.post(
        "/tasks",
        json={"description": "x", "workspace": WORKSPACE},
        headers={"Idempotency-Key": "k" * 201},
    )

    assert response.status_code == 422


async def test_identical_bodies_without_a_key_reconcile_by_derivation(wired) -> None:
    """Derivation is what protects the client that never heard of keys."""
    queue, _run_store, app = wired
    client = _client(app)
    body = {"description": "byte-identical retry", "workspace": WORKSPACE}

    first = client.post("/tasks", json=body)
    retry = client.post("/tasks", json=body)

    assert first.status_code == 202
    assert retry.status_code == 202
    assert retry.json()["task_id"] == first.json()["task_id"]
    assert retry.json()["run_id"] == first.json()["run_id"]
    receipts, _cursor = queue.list_tasks(user_id="dev")
    assert len(receipts) == 1


async def test_two_callers_sharing_a_textual_key_get_their_own_runs(wired) -> None:
    """Scoping is keyed on the authenticated principal: the same key admits
    twice across callers, and neither can read the other's work through it."""
    _queue, _run_store, app = wired
    settings = Settings(api_keys=["alice:alice-secret", "bob:bob-secret"])
    app.dependency_overrides[get_settings] = lambda: settings
    alice = _client(app)
    bob = _client(app)
    body = {"description": "same payload", "workspace": WORKSPACE}

    alices = alice.post(
        "/tasks",
        json=body,
        headers={"Idempotency-Key": "shared", "Authorization": "Bearer alice-secret"},
    )
    bobs = bob.post(
        "/tasks",
        json=body,
        headers={"Idempotency-Key": "shared", "Authorization": "Bearer bob-secret"},
    )

    assert alices.status_code == 202
    assert bobs.status_code == 202
    assert alices.json()["task_id"] != bobs.json()["task_id"]
    assert alices.json()["run_id"] != bobs.json()["run_id"]
    # The scoping cannot be turned into a read either: the receipt is
    # owner-scoped, so bob's authenticated GET of alice's task is a 404, and
    # an unauthenticated one never even reaches the receipt.
    assert bob.get(f"/tasks/{alices.json()['task_id']}").status_code == 401
    assert (
        bob.get(
            f"/tasks/{alices.json()['task_id']}",
            headers={"Authorization": "Bearer bob-secret"},
        ).status_code
        == 404
    )
    assert (
        alice.get(
            f"/tasks/{bobs.json()['task_id']}",
            headers={"Authorization": "Bearer alice-secret"},
        ).status_code
        == 404
    )


async def test_no_key_at_all_behaves_exactly_as_before(wired) -> None:
    """Parity: distinct submissions stay distinct without an explicit key."""
    _queue, _run_store, app = wired
    client = _client(app)

    first = client.post("/tasks", json={"description": "one", "workspace": WORKSPACE})
    second = client.post("/tasks", json={"description": "two", "workspace": WORKSPACE})

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["task_id"] != first.json()["task_id"]
    assert second.json()["run_id"] != first.json()["run_id"]
    assert "Location" in first.headers


# ── the durable wire: claims that outlive the process ─────────────


async def _sqlite_claims(tmp_path: Path, name: str = "claims.db") -> SqliteTaskIdempotencyStore:
    """A claim tier on a real file — the durability a restart is measured
    against. Each call opens its own connection, which is what distinct
    processes (or replicas) actually are."""
    conn = await aiosqlite.connect(tmp_path / name)
    store = SqliteTaskIdempotencyStore(conn)
    await store.ensure_schema()
    return store


@pytest.fixture
async def durable(tmp_path) -> AsyncIterator[tuple[AsyncClient, object, object, Path]]:
    """The HTTP app on the SQLite claim tier, on one loop so the ASGI
    transport and the file's connection share it — the shape a durable
    single-conductor deployment actually wires."""
    previous = queue_module._queue
    queue_module._queue = None
    store = await _sqlite_claims(tmp_path)
    (
        _scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="test-workspace")
    configure_task_queue(admitter=admitter, idempotency_store=store)
    app = FastAPI()
    app.include_router(tasks_router)
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield client, run_store, admitter, tmp_path
    finally:
        await client.aclose()
        queue_module._queue = previous


async def test_a_restart_replay_reconciles_a_completed_admission(durable) -> None:
    """Restart replay of a *completed* admission: the first call was answered
    202 (the client simply never re-polled before the deployment restarted);
    the restarted queue reconstructs the original receipt and Run because the
    claim outlived the process — and re-enqueues the reconciled work, so a
    Run queued before the restart is executable after it, not stranded. The
    full timeout/mid-admission-crash shape is
    ``test_a_mid_admission_timeout_across_a_durable_restart_resumes_the_work``
    below, on the fully durable tier."""
    client, run_store, admitter, tmp_path = durable
    body = {"description": "restart me", "workspace": WORKSPACE}

    first = await client.post("/tasks", json=body, headers={"Idempotency-Key": "k-1"})
    assert first.status_code == 202
    original_run = first.json()["run_id"]

    # The restart: the in-memory receipts and the runner queue are gone; the
    # claim file is not. A fresh queue wires up over the same store.
    reset_task_queue()
    restarted_store = await _sqlite_claims(tmp_path)
    configure_task_queue(admitter=admitter, idempotency_store=restarted_store)

    retry = await client.post("/tasks", json=body, headers={"Idempotency-Key": "k-1"})

    assert retry.status_code == 202
    assert retry.json()["task_id"] == first.json()["task_id"]
    assert retry.json()["run_id"] == original_run
    # The reconstructed receipt is the receipt the first call got — header
    # key included, not forgotten because it never lived in a request body.
    assert retry.json()["task"]["idempotency_key"] == "k-1"
    assert retry.json()["task"]["status"] == "queued"
    # And nothing minted: the spine holds exactly the one Run.
    assert len(run_store._runs) == 1


async def test_a_derived_key_reconciles_across_a_restart(durable) -> None:
    """The client that never heard of keys still gets its timeout-retry
    reconciled after a restart: the payload fingerprint is recomputable from
    the body, so the derived claim is found again."""
    client, run_store, admitter, tmp_path = durable
    body = {"description": "no keys here", "workspace": WORKSPACE}

    first = await client.post("/tasks", json=body)
    assert first.status_code == 202
    reset_task_queue()
    configure_task_queue(admitter=admitter, idempotency_store=await _sqlite_claims(tmp_path))

    retry = await client.post("/tasks", json=body)

    assert retry.status_code == 202
    assert retry.json()["task_id"] == first.json()["task_id"]
    assert retry.json()["run_id"] == first.json()["run_id"]
    assert len(run_store._runs) == 1


async def test_concurrent_http_retries_mint_one_run(durable) -> None:
    """Concurrent-retry E2E: five identical in-flight POSTs meet at one
    durable claim row; exactly one Run exists and every caller holds its
    receipt."""
    client, run_store, _admitter, _tmp_path = durable
    body = {"description": "five racing retries", "workspace": WORKSPACE}
    headers = {"Idempotency-Key": "k-race"}

    responses = list(
        await asyncio.gather(*[client.post("/tasks", json=body, headers=headers) for _ in range(5)])
    )

    assert all(r.status_code == 202 for r in responses)
    task_ids = {r.json()["task_id"] for r in responses}
    run_ids = {r.json()["run_id"] for r in responses}
    assert len(task_ids) == 1
    assert len(run_ids) == 1
    runs_from_tasks = [
        run
        for run in run_store._runs.values()
        if run.provenance.get("admission_source") == "task_queue"
    ]
    assert [run.run_id for run in runs_from_tasks] == list(run_ids)


async def test_a_replica_handoff_reconciles_the_first_replicas_claim(durable) -> None:
    """Replica-handoff E2E: the retry lands on a second replica — its own
    connection to the same claim file — and reconciles to the first replica's
    admission instead of minting a second Run."""
    client, run_store, admitter, tmp_path = durable
    body = {"description": "handed off", "workspace": WORKSPACE}

    first = await client.post("/tasks", json=body, headers={"Idempotency-Key": "k-9"})
    assert first.status_code == 202

    # Replica B: its own claim-store connection to the same file, its own
    # process-worth of lost receipts, the same claim durability.
    reset_task_queue()
    replica_b_store = await _sqlite_claims(tmp_path)
    configure_task_queue(admitter=admitter, idempotency_store=replica_b_store)

    retry = await client.post("/tasks", json=body, headers={"Idempotency-Key": "k-9"})

    assert retry.status_code == 202
    assert retry.json()["task_id"] == first.json()["task_id"]
    assert retry.json()["run_id"] == first.json()["run_id"]
    assert retry.json()["task"]["idempotency_key"] == "k-9"
    assert len(run_store._runs) == 1


# ── the fully durable wire: Runs that survive the restart too ──────


async def _sqlite_spine(
    tmp_path: Path,
) -> tuple[aiosqlite.Connection, object, object]:
    """A Run spine on a real SQLite file — the durability a Run restart is
    measured against. Returns (connection, run_store, routing admitter)."""
    conn = await aiosqlite.connect(tmp_path / "runs.db")
    _scope, run_store, admitter, _t, _s, _c = await wire_execution_spine(
        conn, workspace_id="test-workspace"
    )
    return conn, run_store, admitter


@pytest.fixture
async def durable_spine(tmp_path) -> AsyncIterator[tuple[AsyncClient, Path]]:
    """The HTTP app on the fully durable tier: SQLite claim file AND SQLite
    Run spine, each 'process' opening its own connections to the same files.
    A restart here loses only what a real restart loses."""
    previous = queue_module._queue
    queue_module._queue = None
    claims = await _sqlite_claims(tmp_path)
    _runs_conn, _run_store, admitter = await _sqlite_spine(tmp_path)
    configure_task_queue(admitter=admitter, idempotency_store=claims)
    app = FastAPI()
    app.include_router(tasks_router)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    try:
        yield client, tmp_path
    finally:
        await client.aclose()
        queue_module._queue = previous


async def test_a_mid_admission_timeout_across_a_durable_restart_resumes_the_work(
    durable_spine,
) -> None:
    """The timeout/restart E2E the contract exists for, on the fully durable
    tier: the first submission dies mid-admission *after* minting and queuing
    its Run but before recording the outcome — the client's timeout cancels a
    request that never answered, which is the ambiguous crash-after-create
    window. The deployment restarts over the same durable files; the retry
    must reconcile to the SAME Run (discovery, by the announced receipt), and
    the restarted queue must actually hold the work: a receipt that says
    ``queued`` while no queue holds the Run is a reconciliation that silently
    loses the task."""
    client, tmp_path = durable_spine
    body = {"description": "timeout then crash then retry", "workspace": WORKSPACE}

    queue = queue_module._queue
    assert queue is not None
    store = queue._idempotency
    assert store is not None
    hang = asyncio.Event()

    async def complete_then_hang(scope_key: str, **kwargs: object) -> bool:
        # Death in the instant after the Run was minted and queued, before
        # the outcome was recorded — the write never lands and the receipt is
        # never enqueued.
        await hang.wait()
        return True

    real_complete = store.complete
    store.complete = complete_then_hang  # type: ignore[method-assign]
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            client.post("/tasks", json=body, headers={"Idempotency-Key": "k-1"}),
            timeout=0.3,
        )
    store.complete = real_complete  # type: ignore[method-assign]

    # The crash state, read from the durable files (the 'process' is gone):
    # the claim was begun but its outcome never landed, and the Run it minted
    # is queued and discoverable by the announced receipt.
    scope = admission_scope_key(
        principal="dev",
        workspace_id="test-workspace",
        action=TASK_SUBMIT_ACTION,
        key="k-1",
    )
    corpse_store = await _sqlite_claims(tmp_path)
    record = await corpse_store.get(scope)
    assert record is not None
    assert record.begun and not record.admitted
    assert record.task_id is not None
    # The claim cannot name the Run yet — only `complete`/`resolve_run` write
    # that column — so discovery goes by the announced receipt.
    _runs_conn, run_store, _admitter = await _sqlite_spine(tmp_path)
    crashed_run = await run_store.find_run_by_task_receipt(record.task_id)
    assert crashed_run is not None and crashed_run.status is RunStatus.QUEUED
    run_id = crashed_run.run_id

    # The restart: fresh queue, fresh spine and claim connections over the
    # same files. The outage spanned the pending lease, so the begun claim is
    # the ambiguous case on the retry, resolved by discovery.
    reset_task_queue()
    restarted_claims = await _sqlite_claims(tmp_path)
    _conn2, restarted_runs, restarted_admitter = await _sqlite_spine(tmp_path)
    configure_task_queue(admitter=restarted_admitter, idempotency_store=restarted_claims)
    raw = await aiosqlite.connect(tmp_path / "claims.db")
    await raw.execute("UPDATE task_idempotency SET lease_expires_at = 1")
    await raw.commit()
    await raw.close()

    retry = await client.post("/tasks", json=body, headers={"Idempotency-Key": "k-1"})

    assert retry.status_code == 202
    # The same admission, reconciled by discovery — the client that timed out
    # never saw these ids; the claim's own announcement and the Run its
    # provenance named are what the retry resolved to, so equality here is
    # the no-duplicate guarantee on the wire.
    assert retry.json()["task_id"] == record.task_id
    assert retry.json()["run_id"] == run_id
    assert retry.json()["task"]["idempotency_key"] == "k-1"
    assert retry.json()["task"]["status"] == "queued"
    # Discovery recorded the Run on the claim, so later replays skip it.
    resolved = await restarted_claims.get(scope)
    assert resolved is not None and resolved.admitted and resolved.run_id == run_id
    # And the work is genuinely queued on the restarted deployment: the Run is
    # QUEUED and the queue hands the receipt to a runner.
    restarted_queue = queue_module._queue
    assert restarted_queue is not None
    resumed = await restarted_runs.get_run(run_id)
    assert resumed is not None and resumed.status is RunStatus.QUEUED
    assert await asyncio.wait_for(restarted_queue.next_task(), timeout=1) == record.task_id
    discovered = await restarted_runs.find_run_by_task_receipt(record.task_id)
    assert discovered is not None and discovered.run_id == run_id


# ── the CORS boundary: the idempotency key must reach a browser client ──


def test_the_idempotency_key_header_is_allowed_cross_origin() -> None:
    """The Idempotency-Key header must survive CORS preflight — without it, a
    browser client that retries a task submission cannot send the key that
    reconciles the retry, and the preflight returns 400 Disallowed CORS
    headers. The workspace-scope headers carry the same requirement: the
    Conductor's cross-origin boundary is trusted Hive, and it carries the
    Workspace binding on those headers.

    These wire-level tests mount only the router (no middleware), so they
    cannot catch a CORS omission — this inspects the production app's own
    CORSMiddleware configuration, the same seam
    ``test_the_run_id_header_is_readable_cross_origin`` guards for the Run-Id
    header.
    """
    from maistro.tasks.http_contract import (
        IDEMPOTENCY_KEY_HEADER,
        WORKSPACE_ID_HEADER,
        WORKSPACE_SCOPE_SIGNATURE_HEADER,
    )
    from maistro_server.main import app

    cors = [m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"]
    assert cors, "the app no longer installs CORSMiddleware"
    allow_headers = set(cors[0].kwargs["allow_headers"])
    assert IDEMPOTENCY_KEY_HEADER in allow_headers
    assert WORKSPACE_ID_HEADER in allow_headers
    assert WORKSPACE_SCOPE_SIGNATURE_HEADER in allow_headers
