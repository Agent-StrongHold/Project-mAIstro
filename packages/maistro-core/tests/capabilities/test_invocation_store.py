from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    Invocation,
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


async def _executor(_provider: _Provider, _request: object) -> str:
    return "committed"


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


# Coverage for `maistro.capabilities.pg_invocation_store.PgInvocationStore` --
# the actual PostgreSQL store the container wires (#1079 Finding 3) -- lives
# in `test_pg_invocation_store.py`. This module used to also define and test
# a duplicate `PgInvocationStore` here; it wrote columns (`payload_json`, a
# `datetime` timestamp) that never matched Alembic revision 035's real DDL
# (`payload` JSONB, `created_at` a float) and nothing in production wired it,
# so it was removed rather than fixed.


@pytest.mark.asyncio
async def test_sqlite_list_effect_without_node_run_id_spans_node_runs(tmp_path) -> None:
    """``node_run_id=None`` is the logical-effect identity (#1194): one
    history per (run, binding, effect_key) across every physical NodeRun,
    while a concrete ``node_run_id`` still scopes to one physical visit."""
    db_path = tmp_path / "invocations.db"
    async with aiosqlite.connect(db_path) as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        binding = Binding(
            binding_id="binding-1",
            workspace_id="ws-1",
            project_id="project-1",
            capability="external_write",
        )
        resolved = ResolvedBinding.from_provider(binding, _Provider())
        await store.create(
            Invocation(
                invocation_id="inv-1",
                run_id="run-1",
                node_run_id="node-run-1",
                attempt_id="attempt-1",
                binding=resolved,
                effect_key="write:logical",
            )
        )
        await store.create(
            Invocation(
                invocation_id="inv-2",
                run_id="run-1",
                node_run_id="node-run-2",
                attempt_id="attempt-2",
                binding=resolved,
                effect_key="write:logical",
            )
        )

        logical = await store.list_effect(
            run_id="run-1",
            node_run_id=None,
            binding_id="binding-1",
            effect_key="write:logical",
        )
        visit = await store.list_effect(
            run_id="run-1",
            node_run_id="node-run-2",
            binding_id="binding-1",
            effect_key="write:logical",
        )

    assert [item.invocation_id for item in logical] == ["inv-1", "inv-2"]
    assert [item.invocation_id for item in visit] == ["inv-2"]


@pytest.mark.asyncio
async def test_invoke_race_reread_without_a_completed_winner_re_raises() -> None:
    """A stale admission is only replayable when the winner is provably done.

    When the canonical re-read finds no COMPLETED Invocation -- the winner is
    still RUNNING, or never landed at all -- the original ``UnsafeEffectRetry``
    stands: swallowing it would report an outcome nobody recorded.
    """

    class _RacyStore:
        def __init__(self) -> None:
            self.create_calls = 0

        async def list_effect(
            self, *, run_id: str, node_run_id: str | None, binding_id: str, effect_key: str
        ) -> list[Invocation]:
            return []

        async def create(self, invocation: Invocation) -> Invocation:
            self.create_calls += 1
            raise UnsafeEffectRetry("effect 'write:race' already has an active Invocation")

    store = _RacyStore()
    service = InvocationExecutionService(store=store)  # type: ignore[arg-type]

    with pytest.raises(UnsafeEffectRetry, match="active Invocation"):
        await service.invoke(
            binding=Binding(
                binding_id="binding-1",
                workspace_id="ws-1",
                project_id="project-1",
                capability="external_write",
            ),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="write:race",
            request={"value": 1},
            resolver=_resolver,
            executor=_executor,
        )

    assert store.create_calls == 1
