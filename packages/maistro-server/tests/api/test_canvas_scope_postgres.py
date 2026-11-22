"""E2E over real PostgreSQL: the Canvas image scope chain (#2464).

The defect this pins: ``start_canvas_job_runner`` registered the
``canvas-image-gateway`` Binding under the caller's settings Workspace and a
fabricated ``project_id="default"``, while the runner executed — and every
Canvas Run was admitted into — the chat admission scope's Root Project. The
governed image Invocation then filed its Workspace/Project (taken from the
Binding) under a scope no admitted Run belonged to, and a fixed global
Binding id gave concurrent deployments on one database a single shared
authorization to fight over.

What must hold, on the stores production actually wires (PgRunStore,
PgBindingStore/PgInvocationStore/PgEventStore via ``new_postgres_effect_context``,
PgCanvasStore, all under one migrated database):

1. Run → NodeRun → Attempt → Binding → Invocation carry one Workspace/Project
   — a *non-default* one, minted per tenant — and the Invocation's persisted
   scope and resolved-Binding snapshot name the Run's scope, the physical
   Attempt, and the scope-qualified Binding id.
2. A restart against the same database reuses the persisted Binding (no
   re-registration) and files the next Invocation under the same scope.
3. Two tenants on the same database hold distinct Bindings; neither
   Invocation borrows the other tenant's scope.
4. A Run from a foreign scope claimed by another tenant's runner is refused
   before provider dispatch: the attempt fails truthfully, no Invocation row
   is written, and the gateway sees no image request.

Skips without ``MAISTRO_TEST_PG_DSN``; ``MAISTRO_REQUIRE_PG_LEGS`` turns that
skip into a failure (same contract as the supported-path E2E).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from maistro.capabilities.image_generation import IMAGE_GENERATE_CAPABILITY
from maistro.http import override_transport
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.pg_store import PgRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.testing.postgres import postgres_dsn
from maistro_server.canvas_runtime import (
    CANVAS_IMAGE_BINDING_ID,
    canvas_image_binding_id,
    start_canvas_job_runner,
    stop_canvas_job_runner,
)

ROOT = Path(__file__).resolve().parents[4]

#: A real 1x1 PNG — the stub gateway returns bytes the governed egress will
#: decode, digest and store, so nothing here fakes the payload contract.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

ENDPOINT_BASE = "http://gateway.test"
PROBE_MODEL = "probe-model"

#: The Canvas org (its own tenant id under #857) each tenant's receipts use.
ORG_A = "org-scope-a"
ORG_B = "org-scope-b"

_JOB_TIMEOUT_S = 30.0


# ── PostgreSQL plumbing (same contract as the supported-path E2E) ────────


def _require_pg() -> str:
    dsn = postgres_dsn()
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the Canvas scope E2E cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the Canvas scope E2E needs a real server")


def _sync_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _async_dsn(url: str) -> str:
    return _sync_dsn(url).replace("postgresql://", "postgresql+asyncpg://", 1)


def _execute(url: str, sql: str, *, autocommit: bool = False) -> list[tuple[object, ...]]:
    import psycopg

    with psycopg.connect(_sync_dsn(url), autocommit=autocommit) as conn, conn.cursor() as cur:
        cur.execute(sql)  # type: ignore[arg-type]
        return list(cur.fetchall()) if cur.description else []


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[str]:
    """An empty database migrated by the authoritative root chain only."""
    from sqlalchemy.engine import make_url

    dsn = _require_pg()
    name = f"canvas_scope_{uuid.uuid4().hex[:12]}"
    _execute(dsn, f'CREATE DATABASE "{name}"', autocommit=True)
    url = make_url(dsn).set(database=name).render_as_string(hide_password=False)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": _sync_dsn(url)},
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"
        tables = {
            str(row[0])
            for row in _execute(url, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        missing = {
            "canvases",
            "layers",
            "generation_jobs",
            "canvas_blobs",
            "capability_bindings",
            "capability_invocations",
            "canonical_runs",
            "canonical_node_runs",
            "canonical_attempts",
        } - tables
        assert not missing, f"root chain left the scope E2E no tables: {missing}"
        yield url
    finally:
        _execute(dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', autocommit=True)


class _GatewayStub:
    """The gateway behind the governed egress: a real HTTP-shaped double.

    Serves ``/v1/models`` (the registry's admission list) and the OpenAI-shaped
    image generation the governed egress posts; every request is recorded so
    the negative tests can prove the provider was never reached.
    """

    def __init__(self) -> None:
        self.image_requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": PROBE_MODEL}]})
        if request.url.path == "/v1/images/generations":
            self.image_requests += 1
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"b64_json": base64.b64encode(_PNG).decode(), "revised_prompt": "dawn"}
                    ]
                },
            )
        return httpx.Response(404, json={"error": f"unrouted {request.url.path}"})


class _AdmissionScope:
    """The chat admission scope a Container authorizes (#2464's authority)."""

    def __init__(self, workspace_id: str, project_id: str) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id

    async def admission_scope(self) -> tuple[str, str]:
        return self.workspace_id, self.project_id


class _Container:
    """The Container surface ``start_canvas_job_runner`` consumes, over the
    real PostgreSQL effect authority and run store."""

    def __init__(self, effects: Any, run_store: Any, scope: _AdmissionScope) -> None:
        self.capability_effects = effects
        self.run_store = run_store
        self.chat_admitter = scope


class _Tenant:
    """One Workspace + its Root Project + the stores scoped to them."""

    def __init__(self, pool: Any, engine: AsyncEngine, label: str) -> None:
        self._pool = pool
        self._engine = engine
        self.label = label

    async def admit_scope(self) -> _AdmissionScope:
        projects = PgProjectScopeStore(self._pool)
        workspace_id = f"canvas-scope-{self.label}-{uuid.uuid4().hex[:8]}"
        root = await projects.create_root(workspace_id)
        # Minted, never "default": the assertion underneath is the whole point
        # of the issue, so the fixture refuses to look like the old defect.
        assert root.project_id != "default"
        return _AdmissionScope(workspace_id, root.project_id)

    def run_store(self) -> PgRunStore:
        return PgRunStore(self._pool, project_store=PgProjectScopeStore(self._pool))

    def container(self, effects: Any, scope: _AdmissionScope) -> _Container:
        return _Container(effects, self.run_store(), scope)

    def authorize_gateway_credential(self, effects: Any, scope: _AdmissionScope) -> None:
        """Register the gateway secret under the Binding's credential ref.

        The same registration the Container composition root performs for its
        own scope (``_wire_model_gateway``), scoped to the tenant's
        Workspace/Project: credential routing acquires per-scope, so a key
        registered elsewhere is a refusal, never a fallback."""
        from maistro.capabilities.providers.llm_gateway import (
            DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            MODEL_GATEWAY_CREDENTIAL_PROVIDER,
        )
        from maistro.credentials.types import CredentialRecord

        effects.credentials.add(
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            record=CredentialRecord(
                key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
                provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
                api_key="key",
            ),
        )


@pytest.fixture()
async def database(migrated_database: str) -> AsyncIterator[tuple[str, AsyncEngine]]:
    async_dsn = _async_dsn(migrated_database)
    engine = create_async_engine(async_dsn)
    yield async_dsn, engine
    await engine.dispose()


async def _wait_for_terminal(store: Any, job_id: str, org_id: str) -> Any:
    """Poll the durable receipt until a terminal status, or fail the test."""
    from maistro_canvas.types import JobStatus

    terminal = {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}
    deadline = asyncio.get_running_loop().time() + _JOB_TIMEOUT_S
    while asyncio.get_running_loop().time() < deadline:
        job = await store.get_job(job_id, org_id=org_id)
        assert job is not None, f"receipt {job_id!r} disappeared"
        if job.status in terminal:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError(f"receipt {job_id!r} never terminalized within {_JOB_TIMEOUT_S}s")


def _decoded(row: Any) -> dict[str, Any]:
    """One asyncpg row with its JSONB payload decoded.

    This test pool does not register the JSON codecs production does, so the
    payload arrives as a JSON string; decode either shape.
    """
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return dict(row) | {"payload": payload}


async def _invocation_rows(pool: Any, run_id: str) -> list[dict[str, Any]]:
    """The durable Invocation rows for one Run, payloads decoded."""
    rows = await pool.fetch(
        """
        SELECT invocation_id, run_id, node_run_id, attempt_id, binding_id,
               effect_key, status, payload
        FROM capability_invocations WHERE run_id = $1 ORDER BY created_at
        """,
        run_id,
    )
    return [_decoded(row) for row in rows]


async def _binding_row(pool: Any, binding_id: str) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        SELECT binding_id, workspace_id, project_id, capability, created_at,
               payload_json AS payload
        FROM capability_bindings WHERE binding_id = $1
        """,
        binding_id,
    )
    return _decoded(row) if row else None


# ── 1. One tenant, one generate: the whole scope chain over real rows ────


async def test_run_attempt_binding_and_invocation_share_one_scope(
    database: tuple[str, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    async_dsn, engine = database
    import asyncpg

    from maistro.capabilities.effect_context import new_postgres_effect_context
    from maistro_canvas.types import JobStatus
    from maistro_server.canvas_runtime import CanvasImageBlobStore  # noqa: F401

    pool = await asyncpg.create_pool(
        async_dsn.replace("postgresql+asyncpg://", "postgresql://", 1), min_size=1, max_size=4
    )
    try:
        from maistro_canvas.canvas.store import PgCanvasStore

        effects = await new_postgres_effect_context(pool)
        usage_log = effects.usage_log
        stub = _GatewayStub()
        canvas_store = PgCanvasStore(engine)
        tenant = _Tenant(pool, engine, "a")
        scope = await tenant.admit_scope()
        container = tenant.container(effects, scope)
        tenant.authorize_gateway_credential(effects, scope)
        expected_binding_id = canvas_image_binding_id(scope.workspace_id, scope.project_id)

        canvas = await canvas_store.create_canvas(
            name="scope e2e", width=32, height=32, org_id=ORG_A
        )
        layer = await canvas_store.add_layer(
            canvas.id, name="sky", layer_type="background", org_id=ORG_A
        )

        with override_transport(httpx.MockTransport(stub.handler)):
            handle = await start_canvas_job_runner(
                store=canvas_store,
                container=container,
                endpoint=__import__(
                    "maistro.capabilities.providers.llm_gateway", fromlist=["GatewayEndpoint"]
                ).GatewayEndpoint(base_url=ENDPOINT_BASE, api_key="key"),
                workspace_id=scope.workspace_id,
                worker_id="scope-e2e-a",
            )
            try:
                executor = handle.runtime.executor
                job = await executor.start_job(
                    canvas_id=canvas.id,
                    layer_id=layer.id,
                    org_id=ORG_A,
                    action="generate",
                    model_id=PROBE_MODEL,
                    prompt="a dawn sky",
                    actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
                )
                assert stub.image_requests == 0, "admission dispatches nothing"
                settled = await _wait_for_terminal(canvas_store, job.id, ORG_A)
            finally:
                await stop_canvas_job_runner(handle)

        assert settled.status is JobStatus.DONE, settled.error_message
        assert settled.result_paths, "a completed generation stores its blob references"

        run_id = settled.params.get("canonical_run_id")
        assert isinstance(run_id, str) and run_id, "the receipt must correlate its Run"
        run_store = tenant.run_store()
        run = await run_store.get_run(run_id)
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        # The non-default admission scope, everywhere — this is the defect the
        # issue named: the Invocation used to file "default" beside this Run.
        assert run.workspace_id == scope.workspace_id
        assert run.project_id == scope.project_id

        node_runs = await run_store.list_node_runs(run_id)
        assert node_runs, "the generate stage files a NodeRun"
        completed_attempt: Any = None
        for node_run in node_runs:
            for attempt in await run_store.list_attempts(node_run.node_run_id):
                if attempt.status is AttemptStatus.COMPLETED:
                    completed_attempt = attempt
        assert completed_attempt is not None, "the physical Attempt completed"

        invocations = await _invocation_rows(pool, run_id)
        assert len(invocations) == 1, "one governed effect for one stage"
        invocation = invocations[0]
        assert invocation["status"] == "completed"
        assert invocation["attempt_id"] == completed_attempt.attempt_id, (
            "the Invocation is filed on the exact physical Attempt that ran"
        )
        assert invocation["binding_id"] == expected_binding_id
        payload = invocation["payload"]
        assert payload["workspace_id"] == run.workspace_id
        assert payload["project_id"] == run.project_id
        # The same principal the Run was admitted under (#2464): quota and
        # audit attribute the physical effect to that identity, not "system".
        assert payload["actor_id"] == DEFAULT_TEST_ACTOR_PRINCIPAL_ID
        snapshot = payload["binding"]
        assert snapshot["binding_id"] == expected_binding_id
        assert snapshot["workspace_id"] == run.workspace_id
        assert snapshot["project_id"] == run.project_id
        assert snapshot["capability"] == IMAGE_GENERATE_CAPABILITY

        binding = await _binding_row(pool, expected_binding_id)
        assert binding is not None
        assert binding["workspace_id"] == scope.workspace_id
        assert binding["project_id"] == scope.project_id
        assert binding["capability"] == IMAGE_GENERATE_CAPABILITY
        assert binding["payload"]["workspace_id"] == scope.workspace_id
        assert binding["payload"]["project_id"] == scope.project_id

        # Usage settlement carries the same Invocation identity, so quota and
        # billing evidence resolves back to the Run's scope through the row
        # above rather than through a parallel set of scope columns.
        events = [
            event
            for scope_events in usage_log._scopes.values()
            for event in scope_events.events
            if event.invocation_id == invocation["invocation_id"]
        ]
        assert events, "the completed image effect is settled on the usage ledger"
        # One image settles as one output unit under the Invocation's identity,
        # so settlement correlates back to the Run's scope through the row
        # above rather than through a parallel set of scope columns.
        assert all(event.output_tokens == 1 for event in events)

        # The retired bare-family id must not have been written beside the
        # scope-qualified one.
        assert await _binding_row(pool, CANVAS_IMAGE_BINDING_ID) is None
        assert stub.image_requests == 1, "exactly one provider call for one stage"
    finally:
        await pool.close()


# ── 2. Restart: the persisted Binding stays the authority ────────────────


async def test_restart_reuses_the_scoped_binding_and_files_the_same_scope(
    database: tuple[str, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    async_dsn, engine = database
    import asyncpg

    from maistro.capabilities.effect_context import new_postgres_effect_context
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro_canvas.canvas.store import PgCanvasStore
    from maistro_canvas.types import JobStatus

    pool = await asyncpg.create_pool(
        async_dsn.replace("postgresql+asyncpg://", "postgresql://", 1), min_size=1, max_size=4
    )
    try:
        effects = await new_postgres_effect_context(pool)
        stub = _GatewayStub()
        canvas_store = PgCanvasStore(engine)
        tenant = _Tenant(pool, engine, "restart")
        scope = await tenant.admit_scope()
        container = tenant.container(effects, scope)
        tenant.authorize_gateway_credential(effects, scope)
        binding_id = canvas_image_binding_id(scope.workspace_id, scope.project_id)

        canvas = await canvas_store.create_canvas(
            name="restart e2e", width=32, height=32, org_id=ORG_A
        )
        layer = await canvas_store.add_layer(
            canvas.id, name="sky", layer_type="background", org_id=ORG_A
        )
        endpoint = GatewayEndpoint(base_url=ENDPOINT_BASE, api_key="key")

        async def run_one(worker: str) -> Any:
            with override_transport(httpx.MockTransport(stub.handler)):
                handle = await start_canvas_job_runner(
                    store=canvas_store,
                    container=container,
                    endpoint=endpoint,
                    workspace_id=scope.workspace_id,
                    worker_id=worker,
                )
                try:
                    job = await handle.runtime.executor.start_job(
                        canvas_id=canvas.id,
                        layer_id=layer.id,
                        org_id=ORG_A,
                        action="generate",
                        model_id=PROBE_MODEL,
                        prompt=f"a dawn sky ({worker})",
                        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
                    )
                    return await _wait_for_terminal(canvas_store, job.id, ORG_A)
                finally:
                    await stop_canvas_job_runner(handle)

        first = await run_one("scope-e2e-r1")
        assert first.status is JobStatus.DONE
        before = await _binding_row(pool, binding_id)
        assert before is not None

        # A restart against the same database: the scope-qualified id derives
        # identically, so the first boot's immutable record stays the
        # authority — no re-registration, no scope drift.
        second = await run_one("scope-e2e-r2")
        assert second.status is JobStatus.DONE
        after = await _binding_row(pool, binding_id)
        assert after == before, "the restart must not re-register or reshape the Binding"

        run_store = tenant.run_store()
        for receipt in (first, second):
            run_id = receipt.params["canonical_run_id"]
            run = await run_store.get_run(run_id)
            assert run is not None
            assert run.workspace_id == scope.workspace_id
            assert run.project_id == scope.project_id
            invocations = await _invocation_rows(pool, run_id)
            assert len(invocations) == 1
            assert invocations[0]["binding_id"] == binding_id
            assert invocations[0]["payload"]["workspace_id"] == scope.workspace_id
            assert invocations[0]["payload"]["project_id"] == scope.project_id
        assert stub.image_requests == 2
    finally:
        await pool.close()


# ── 3. Two tenants on one database: distinct bindings, own scopes ────────


async def test_two_tenants_hold_distinct_bindings_and_own_scopes(
    database: tuple[str, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    async_dsn, engine = database
    import asyncpg

    from maistro.capabilities.effect_context import new_postgres_effect_context
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro_canvas.canvas.store import PgCanvasStore
    from maistro_canvas.types import JobStatus

    pool = await asyncpg.create_pool(
        async_dsn.replace("postgresql+asyncpg://", "postgresql://", 1), min_size=1, max_size=4
    )
    try:
        effects = await new_postgres_effect_context(pool)
        stub = _GatewayStub()
        canvas_store = PgCanvasStore(engine)
        endpoint = GatewayEndpoint(base_url=ENDPOINT_BASE, api_key="key")
        tenant_a = _Tenant(pool, engine, "tenanta")
        tenant_b = _Tenant(pool, engine, "tenantb")
        scope_a = await tenant_a.admit_scope()
        scope_b = await tenant_b.admit_scope()
        binding_a = canvas_image_binding_id(scope_a.workspace_id, scope_a.project_id)
        binding_b = canvas_image_binding_id(scope_b.workspace_id, scope_b.project_id)
        assert binding_a != binding_b, "one scope, one Binding identity"

        canvases: dict[str, tuple[Any, Any]] = {}
        for org in (ORG_A, ORG_B):
            canvas = await canvas_store.create_canvas(
                name=f"tenant e2e {org}", width=32, height=32, org_id=org
            )
            layer = await canvas_store.add_layer(
                canvas.id, name="sky", layer_type="background", org_id=org
            )
            canvases[org] = (canvas, layer)

        async def run_tenant(tenant: _Tenant, scope: _AdmissionScope, org: str, worker: str) -> Any:
            tenant.authorize_gateway_credential(effects, scope)
            container = tenant.container(effects, scope)
            with override_transport(httpx.MockTransport(stub.handler)):
                handle = await start_canvas_job_runner(
                    store=canvas_store,
                    container=container,
                    endpoint=endpoint,
                    workspace_id=scope.workspace_id,
                    worker_id=worker,
                )
                try:
                    canvas, layer = canvases[org]
                    job = await handle.runtime.executor.start_job(
                        canvas_id=canvas.id,
                        layer_id=layer.id,
                        org_id=org,
                        action="generate",
                        model_id=PROBE_MODEL,
                        prompt=f"a dawn sky ({org})",
                        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
                    )
                    return await _wait_for_terminal(canvas_store, job.id, org)
                finally:
                    await stop_canvas_job_runner(handle)

        # Sequential by construction: whichever tenant's runner is up claims
        # from the shared queue, and the scope chain below must hold for BOTH
        # receipts regardless of which worker executed them.
        receipt_a = await run_tenant(tenant_a, scope_a, ORG_A, "scope-e2e-ta")
        assert receipt_a.status is JobStatus.DONE
        receipt_b = await run_tenant(tenant_b, scope_b, ORG_B, "scope-e2e-tb")
        assert receipt_b.status is JobStatus.DONE

        for receipt, scope, binding_id in (
            (receipt_a, scope_a, binding_a),
            (receipt_b, scope_b, binding_b),
        ):
            run = await tenant_a.run_store().get_run(receipt.params["canonical_run_id"])
            assert run is not None
            assert run.workspace_id == scope.workspace_id
            assert run.project_id == scope.project_id
            invocations = await _invocation_rows(pool, run.run_id)
            assert len(invocations) == 1
            assert invocations[0]["binding_id"] == binding_id
            assert invocations[0]["payload"]["workspace_id"] == scope.workspace_id
            assert invocations[0]["payload"]["project_id"] == scope.project_id
            binding = await _binding_row(pool, binding_id)
            assert binding is not None
            assert binding["workspace_id"] == scope.workspace_id
            assert binding["project_id"] == scope.project_id
    finally:
        await pool.close()


# ── 4. Negative: a foreign-scope Run cannot spend another tenant's Binding


async def test_a_foreign_scope_run_is_refused_without_provider_dispatch(
    database: tuple[str, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    async_dsn, engine = database
    import asyncpg

    from maistro.capabilities.effect_context import new_postgres_effect_context
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro_canvas.canvas.store import PgCanvasStore
    from maistro_canvas.types import JobStatus

    pool = await asyncpg.create_pool(
        async_dsn.replace("postgresql+asyncpg://", "postgresql://", 1), min_size=1, max_size=4
    )
    try:
        effects = await new_postgres_effect_context(pool)
        stub = _GatewayStub()
        canvas_store = PgCanvasStore(engine)
        endpoint = GatewayEndpoint(base_url=ENDPOINT_BASE, api_key="key")
        tenant_a = _Tenant(pool, engine, "guarda")
        tenant_b = _Tenant(pool, engine, "guardb")
        scope_a = await tenant_a.admit_scope()
        scope_b = await tenant_b.admit_scope()

        canvas_b = await canvas_store.create_canvas(
            name="guard e2e", width=32, height=32, org_id=ORG_B
        )
        layer_b = await canvas_store.add_layer(
            canvas_b.id, name="sky", layer_type="background", org_id=ORG_B
        )

        # B admits its Run into B's scope through its own composition; A's
        # runner is the only consumer on the shared queue, so A claims it.
        admitted: list[Any] = []

        def container_for(tenant: _Tenant, scope: _AdmissionScope) -> _Container:
            tenant.authorize_gateway_credential(effects, scope)
            return tenant.container(effects, scope)

        container_b = container_for(tenant_b, scope_b)
        with override_transport(httpx.MockTransport(stub.handler)):
            starter = await start_canvas_job_runner(
                store=canvas_store,
                container=container_b,
                endpoint=endpoint,
                workspace_id=scope_b.workspace_id,
                worker_id="scope-e2e-b-admitter",
            )
            try:
                job = await starter.runtime.executor.start_job(
                    canvas_id=canvas_b.id,
                    layer_id=layer_b.id,
                    org_id=ORG_B,
                    action="generate",
                    model_id=PROBE_MODEL,
                    prompt="a dawn sky",
                    actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
                )
                admitted.append(job)
            finally:
                await stop_canvas_job_runner(starter)
        assert stub.image_requests == 0, "admission alone dispatches nothing"

        # A's runner (Workspace A) claims B's receipt. The stage binds B's
        # durable Run scope; A's Binding resolves only in A's scope; the
        # governed client refuses before the provider is reached — on every
        # retry, until the receipt terminalizes as FAILED. No Invocation row,
        # no spend, no successful-looking receipt.
        container_a = container_for(tenant_a, scope_a)
        with override_transport(httpx.MockTransport(stub.handler)):
            handle = await start_canvas_job_runner(
                store=canvas_store,
                container=container_a,
                endpoint=endpoint,
                workspace_id=scope_a.workspace_id,
                worker_id="scope-e2e-a-guard",
            )
            try:
                settled = await _wait_for_terminal(canvas_store, admitted[0].id, ORG_B)
            finally:
                await stop_canvas_job_runner(handle)

        assert settled.status is JobStatus.FAILED, settled.status
        run_id = settled.params["canonical_run_id"]
        run = await tenant_b.run_store().get_run(run_id)
        assert run is not None
        assert run.workspace_id == scope_b.workspace_id
        assert run.project_id == scope_b.project_id
        assert run.status in {RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.CANCELLED}
        invocations = await _invocation_rows(pool, run_id)
        assert invocations == [], "a refused effect must not leave an Invocation row behind"
        assert stub.image_requests == 0, "the mismatched Binding must never reach the provider"
        # The receipt's copy is class-sanitized (provider-path errors never
        # carry raw exception text to Canvas consumers), but the canonical
        # Attempt record — the audit evidence for the physical work — must
        # name the authorization refusal truthfully.
        refusal_evidence: list[str] = []
        for node_run in await tenant_b.run_store().list_node_runs(run_id):
            for attempt in await tenant_b.run_store().list_attempts(node_run.node_run_id):
                if attempt.error:
                    refusal_evidence.append(attempt.error)
        assert any(
            "Binding is not authorized" in error and "Workspace/Project scope" in error
            for error in refusal_evidence
        ), f"the Attempt record must name the scope refusal: {refusal_evidence!r}"
    finally:
        await pool.close()
