from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import (
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.container import _wire_capability_invocations


class _Provider:
    name = "provider-a"
    slot = "external_write"
    trust_tier = "trusted"


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


@pytest.mark.asyncio
async def test_sqlite_store_serializes_active_effect_creation_across_connections(tmp_path) -> None:
    db_path = tmp_path / "invocations.db"
    async with aiosqlite.connect(db_path) as first_conn, aiosqlite.connect(db_path) as second_conn:
        stores = [SqliteInvocationStore(first_conn), SqliteInvocationStore(second_conn)]
        await stores[0].ensure_schema()
        await stores[1].ensure_schema()
        binding = Binding(
            binding_id="binding-1",
            workspace_id="ws-1",
            project_id="project-1",
            capability="external_write",
        )
        resolver_calls = 0
        resolver_ready = asyncio.Event()

        async def concurrent_resolver(_binding: Binding) -> _Provider:
            nonlocal resolver_calls
            resolver_calls += 1
            if resolver_calls == 2:
                resolver_ready.set()
            await resolver_ready.wait()
            return _Provider()

        calls = 0

        async def execute(_provider: _Provider, _request: object) -> str:
            nonlocal calls
            calls += 1
            return "committed"

        async def invoke(store: SqliteInvocationStore, attempt_id: str) -> object:
            return await InvocationExecutionService(store=store).invoke(
                binding=binding,
                run_id="run-race",
                node_run_id="node-race",
                attempt_id=attempt_id,
                effect_key="write:race",
                request={"value": 1},
                resolver=concurrent_resolver,
                executor=execute,
            )

        results = await asyncio.gather(
            invoke(stores[0], "attempt-1"),
            invoke(stores[1], "attempt-2"),
            return_exceptions=True,
        )
        history = await stores[0].list_effect(
            run_id="run-race",
            node_run_id="node-race",
            binding_id="binding-1",
            effect_key="write:race",
        )
        # The losing connection must be usable after its guarded rejection;
        # otherwise a failed race can strand every later write on that worker.
        for index, store in enumerate(stores):
            await InvocationExecutionService(store=store).invoke(
                binding=binding,
                run_id="run-after-race",
                node_run_id="node-after-race",
                attempt_id=f"attempt-{index}",
                effect_key=f"write:after-race:{index}",
                request={"value": index},
                resolver=_resolver,
                executor=execute,
            )

    assert all(
        isinstance(result, UnsafeEffectRetry)
        or getattr(result, "status", None) is InvocationStatus.COMPLETED
        for result in results
    )
    assert (
        sum(getattr(result, "status", None) is InvocationStatus.COMPLETED for result in results)
        >= 1
    )
    assert len(history) == 1
    assert calls == 3


async def test_container_wires_capability_store_to_sqlite_connection() -> None:
    async with aiosqlite.connect(":memory:") as conn:
        store = await _wire_capability_invocations(pg_pool=None, db_pool=conn)
        assert isinstance(store, SqliteInvocationStore)
        await store.ensure_schema()


async def test_sqlite_store_preserves_effect_and_resolved_provider_across_reopen(tmp_path) -> None:
    db_path = tmp_path / "invocations.db"
    binding = Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        capability="external_write",
        config={"region": "us"},
    )

    async with aiosqlite.connect(db_path) as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        service = InvocationExecutionService(store=store)

        async def execute(_provider: _Provider, request: object) -> object:
            return {"written": request}

        invocation = await service.invoke(
            binding=binding,
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="write:alpha",
            effect_scope="run-1:node:write:alpha",
            request={"value": 1},
            resolver=_resolver,
            executor=execute,
        )
        assert invocation.status is InvocationStatus.COMPLETED

    async with aiosqlite.connect(db_path) as conn:
        reopened = SqliteInvocationStore(conn)
        await reopened.ensure_schema()
        history = await reopened.list_effect(
            run_id="run-1",
            node_run_id="node-run-2",
            binding_id="binding-1",
            effect_key="write:alpha",
            effect_scope="run-1:node:write:alpha",
        )

    assert len(history) == 1
    persisted = history[0]
    assert persisted.invocation_id == invocation.invocation_id
    assert persisted.binding.provider_name == "provider-a"
    assert persisted.binding.provider_trust_tier == "trusted"
    assert persisted.binding.config == {"region": "us"}
    assert persisted.result == {"written": {"value": 1}}


def _now() -> datetime:
    return datetime.now(UTC)


def _resolved_binding(binding_id: str = "binding-1") -> Any:
    from maistro.capabilities.binding import ResolvedBinding

    binding = Binding(
        binding_id=binding_id,
        workspace_id="ws-1",
        project_id="project-1",
        capability="external_write",
    )
    return ResolvedBinding.from_provider(binding, _Provider())


def _durable_invocation(**overrides: Any) -> Any:
    from maistro.capabilities.invocation import Invocation

    defaults: dict[str, Any] = {
        "invocation_id": "inv-1",
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "binding": _resolved_binding(),
        "effect_key": "charge:order-42",
        "effect_scope": "run-1:charge:order-42",
    }
    defaults.update(overrides)
    return Invocation(**defaults)


@pytest.mark.asyncio
async def test_sqlite_store_rejects_cross_node_run_active_effect_claim(tmp_path) -> None:
    """The durable claim is keyed by the logical effect identity, so a second
    NodeRun visit of the same stable effect cannot create its own Invocation
    while the first visit's outcome is still active (#42, #1194). Only a
    proven-FAILED record -- ``EffectNotApplied`` evidence -- admits a new
    chronological visit."""

    db_path = tmp_path / "invocations.db"
    async with aiosqlite.connect(db_path) as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()

        first = await store.create(
            _durable_invocation(status=InvocationStatus.RUNNING, started_at=_now())
        )
        with pytest.raises(UnsafeEffectRetry, match="active or completed"):
            await store.create(
                _durable_invocation(
                    invocation_id="inv-2",
                    node_run_id="node-run-2",
                    attempt_id="attempt-2",
                )
            )

        # A second visit of the same logical effect is allowed only after the
        # prior record proves the external effect did not occur.
        await store.save(
            first.model_copy(
                update={
                    "status": InvocationStatus.FAILED,
                    "finished_at": _now(),
                    "error": "provider proved effect not applied",
                }
            )
        )
        retry = await store.create(
            _durable_invocation(
                invocation_id="inv-3",
                node_run_id="node-run-3",
                attempt_id="attempt-3",
            )
        )
        history = await store.list_effect(
            run_id="run-1",
            node_run_id="node-run-3",
            binding_id="binding-1",
            effect_key="charge:order-42",
            effect_scope="run-1:charge:order-42",
        )

    assert retry.node_run_id == "node-run-3"
    assert [item.invocation_id for item in history] == ["inv-1", "inv-3"]


@pytest.mark.asyncio
async def test_sqlite_service_deduplicates_logical_effect_across_node_run_visits(
    tmp_path,
) -> None:
    """The durable counterpart of the in-memory contract: a completed prior
    Invocation for the same logical effect is returned to a later NodeRun
    visit without another provider call."""

    db_path = tmp_path / "invocations.db"
    calls = 0

    async def execute(_provider: _Provider, request: object) -> object:
        nonlocal calls
        calls += 1
        return {"written": request}

    async with aiosqlite.connect(db_path) as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        service = InvocationExecutionService(store=store)
        binding = Binding(
            binding_id="binding-1",
            workspace_id="ws-1",
            project_id="project-1",
            capability="external_write",
        )

        async def visit(node_run_id: str, attempt_id: str) -> object:
            return await service.invoke(
                binding=binding,
                run_id="run-1",
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                effect_key="charge:order-42",
                effect_scope="run-1:charge:order-42",
                request={"order": 42},
                resolver=_resolver,
                executor=execute,
            )

        first = await visit("node-run-1", "attempt-1")
        replay = await visit("node-run-2", "attempt-2")

    assert calls == 1
    assert replay.invocation_id == first.invocation_id
    assert replay.node_run_id == "node-run-1"
    assert replay.attempt_id == "attempt-1"


@pytest.mark.asyncio
async def test_sqlite_ensure_schema_migrates_legacy_node_run_scoped_claim(tmp_path) -> None:
    """A database deployed by the pre-scope schema (no ``effect_scope``
    column, node_run_id-keyed claim index) is reconciled in place: legacy rows
    get their logical scope backfilled and the claim index is replaced, so the
    durable store honors the cross-NodeRun contract without a re-migration."""

    db_path = tmp_path / "invocations.db"
    legacy_schema = """
    CREATE TABLE IF NOT EXISTS capability_invocations (
        invocation_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        node_run_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        binding_id TEXT NOT NULL,
        effect_key TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at REAL NOT NULL,
        payload_json TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_capability_invocation_active_effect
        ON capability_invocations (run_id, node_run_id, binding_id, effect_key)
        WHERE status IN ('created', 'running', 'unknown');
    """
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(legacy_schema)
        await conn.execute(
            """INSERT INTO capability_invocations (
                   invocation_id, run_id, node_run_id, attempt_id, binding_id,
                   effect_key, status, created_at, payload_json
               ) VALUES ('inv-legacy', 'run-1', 'node-run-1', 'attempt-0',
                         'binding-1', 'charge:order-42', 'completed', 1.0, '{}')"""
        )
        await conn.commit()

        store = SqliteInvocationStore(conn)
        await store.ensure_schema()

        index_sql = await conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND name = 'uq_capability_invocation_active_effect'"
        )
        row = await index_sql.fetchone()
        assert row is not None and "effect_scope" in str(row[0])

        # The backfilled legacy row is now part of the logical identity: a new
        # visit normalizing to the same scope (empty scope -> node_run_id)
        # cannot create a second active Invocation.
        with pytest.raises(UnsafeEffectRetry, match="active or completed"):
            await store.create(
                _durable_invocation(
                    invocation_id="inv-new",
                    node_run_id="node-run-1",
                    attempt_id="attempt-9",
                    effect_scope="",
                    status=InvocationStatus.CREATED,
                )
            )


# Coverage for `maistro.capabilities.pg_invocation_store.PgInvocationStore` --
# the actual PostgreSQL store the container wires (#1079 Finding 3) -- lives
# in `test_pg_invocation_store.py`. This module used to also define and test
# a duplicate `PgInvocationStore` here; it wrote columns (`payload_json`, a
# `datetime` timestamp) that never matched Alembic revision 035's real DDL
# (`payload` JSONB, `created_at` a float) and nothing in production wired it,
# so it was removed rather than fixed.
