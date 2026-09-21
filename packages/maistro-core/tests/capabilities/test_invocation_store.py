from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import PgInvocationStore, SqliteInvocationStore
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
            node_run_id="node-run-1",
            binding_id="binding-1",
            effect_key="write:alpha",
        )

    assert len(history) == 1
    persisted = history[0]
    assert persisted.invocation_id == invocation.invocation_id
    assert persisted.binding.provider_name == "provider-a"
    assert persisted.binding.provider_trust_tier == "trusted"
    assert persisted.binding.config == {"region": "us"}
    assert persisted.result == {"written": {"value": 1}}


# --- PgInvocationStore: same InvocationStore contract, over an asyncpg-shaped
# pool (#1091). Distinct from `maistro.capabilities.pg_invocation_store`,
# which the container actually wires for PostgreSQL -- this class stays
# public API (`__all__`) so it is tested directly rather than through the
# container's composition. -------------------------------------------------


def _resolved_binding(binding_id: str = "binding-1") -> ResolvedBinding:
    binding = Binding(
        binding_id=binding_id,
        workspace_id="ws-1",
        project_id="project-1",
        capability="external_write",
    )
    return ResolvedBinding.from_provider(binding, _Provider())


def _invocation(**overrides: Any) -> Invocation:
    defaults: dict[str, Any] = {
        "invocation_id": "inv-1",
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "binding": _resolved_binding(),
        "effect_key": "test:pg-store",
    }
    defaults.update(overrides)
    return Invocation(**defaults)


class _FakePgInvocationPool:
    """Records the exact INSERT/UPDATE/SELECT shape `PgInvocationStore`
    issues, standing in for a live asyncpg pool the way `_FakePgBindingPool`
    does for `PgBindingStore` in `test_binding_invocation.py`."""

    def __init__(self) -> None:
        self._rows: dict[str, str] = {}

    async def fetchval(self, query: str, *args: Any) -> str | None:
        if "INSERT INTO" in query:
            invocation_id, payload_json = args[0], args[-1]
            if invocation_id in self._rows:
                return None
            self._rows[invocation_id] = payload_json
            return invocation_id
        if "UPDATE capability_invocations" in query:
            payload_json, invocation_id = args[-2], args[-1]
            if invocation_id not in self._rows:
                return None
            self._rows[invocation_id] = payload_json
            return invocation_id
        if "SELECT payload_json" in query:
            return self._rows.get(args[0])
        raise AssertionError(f"unexpected query: {query!r}")

    async def fetch(self, _query: str, *args: Any) -> list[dict[str, Any]]:
        run_id, node_run_id, binding_id, effect_key = args
        matches = []
        for payload_json in self._rows.values():
            row = Invocation.model_validate_json(payload_json)
            if (
                row.run_id == run_id
                and row.node_run_id == node_run_id
                and row.binding.binding_id == binding_id
                and row.effect_key == effect_key
            ):
                matches.append({"payload_json": payload_json})
        return matches

    def seed(self, invocation: Invocation) -> None:
        self._rows[invocation.invocation_id] = invocation.model_dump_json()


async def test_pg_invocation_store_create_persists_and_get_round_trips() -> None:
    store = PgInvocationStore(_FakePgInvocationPool())
    invocation = _invocation()

    created = await store.create(invocation)

    assert created.invocation_id == invocation.invocation_id
    fetched = await store.get(invocation.invocation_id)
    assert fetched is not None
    assert fetched.invocation_id == invocation.invocation_id
    assert fetched.effect_key == invocation.effect_key
    assert await store.get("inv-absent") is None


async def test_pg_invocation_store_create_conflict_raises_value_error() -> None:
    pool = _FakePgInvocationPool()
    pool.seed(_invocation())
    store = PgInvocationStore(pool)

    with pytest.raises(ValueError, match="already exists"):
        await store.create(_invocation())


async def test_pg_invocation_store_save_updates_and_returns_copy() -> None:
    pool = _FakePgInvocationPool()
    store = PgInvocationStore(pool)
    await store.create(_invocation())

    updated = await store.save(_invocation(status=InvocationStatus.RUNNING))

    assert updated.status is InvocationStatus.RUNNING
    persisted = await store.get("inv-1")
    assert persisted is not None
    assert persisted.status is InvocationStatus.RUNNING


async def test_pg_invocation_store_save_of_missing_invocation_raises_key_error() -> None:
    store = PgInvocationStore(_FakePgInvocationPool())

    with pytest.raises(KeyError, match="does not exist"):
        await store.save(_invocation())


async def test_pg_invocation_store_list_effect_filters_and_orders_rows() -> None:
    pool = _FakePgInvocationPool()
    store = PgInvocationStore(pool)
    await store.create(_invocation(invocation_id="inv-1", effect_key="test:pg-store"))
    await store.create(
        _invocation(
            invocation_id="inv-2",
            binding=_resolved_binding("binding-2"),
            effect_key="test:other-effect",
        )
    )

    history = await store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="binding-1",
        effect_key="test:pg-store",
    )

    assert [item.invocation_id for item in history] == ["inv-1"]
