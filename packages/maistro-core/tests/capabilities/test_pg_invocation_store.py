"""Coverage for the PostgreSQL capability Invocation store the container
actually wires: `maistro.capabilities.pg_invocation_store.PgInvocationStore`
(#1079 Finding 3).

Exercised against a fake asyncpg-shaped pool whose query/row shapes mirror
this store's real SQL -- `payload` (JSONB) and `created_at` (a float),
matching Alembic revision 035's actual DDL. `test_invocation_store.py` used
to carry an equivalent suite against a *different*, unwired `PgInvocationStore`
defined in `maistro.capabilities.invocation_store`; that class wrote columns
(`payload_json`, a `datetime` timestamp) that never matched migration 035 and
nothing in production wired it, so it was removed rather than fixed, and this
file exists so the store the container actually uses keeps direct coverage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.pg_invocation_store import PgInvocationStore
from maistro.container import _wire_capability_invocations


class _Provider:
    name = "provider-a"
    slot = "external_write"
    trust_tier = "trusted"


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


class _Row(dict):
    """asyncpg rows are mapping-like; a plain dict subclass is enough here."""


class _FakePgInvocationPool:
    """Records the exact INSERT/UPDATE/SELECT shape `PgInvocationStore`
    issues against `payload`/`created_at`, matching migration 035's DDL --
    standing in for a live asyncpg pool the way `_FakePgBindingPool` does for
    `PgBindingStore` in `test_binding_invocation.py`."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    async def fetchrow(self, query: str, *args: Any) -> _Row | None:
        if "INSERT INTO" in query:
            invocation_id = args[0]
            if invocation_id in self._rows:
                return None
            self._rows[invocation_id] = {
                "invocation_id": invocation_id,
                "run_id": args[1],
                "node_run_id": args[2],
                "attempt_id": args[3],
                "binding_id": args[4],
                "effect_key": args[5],
                "status": args[6],
                "revision": args[7],
                "created_at": args[8],
                "payload": args[9],
            }
            return _Row(invocation_id=invocation_id)
        if "ORDER BY created_at DESC" in query:
            # `_find_effect`: latest row for this run/node/binding/effect_key.
            run_id, node_run_id, binding_id, effect_key = args
            matches = [
                row
                for row in self._rows.values()
                if row["run_id"] == run_id
                and row["node_run_id"] == node_run_id
                and row["binding_id"] == binding_id
                and row["effect_key"] == effect_key
            ]
            return _Row(payload=matches[-1]["payload"]) if matches else None
        if "SELECT payload FROM capability_invocations WHERE invocation_id" in query:
            row = self._rows.get(args[0])
            return _Row(payload=row["payload"]) if row is not None else None
        raise AssertionError(f"unexpected query: {query!r}")

    async def execute(self, query: str, *args: Any) -> str:
        if "UPDATE capability_invocations" in query:
            invocation_id, revision = args[-2], args[-1]
            existing = self._rows.get(invocation_id)
            if existing is None or existing["revision"] != revision:
                return "UPDATE 0"
            self._rows[invocation_id] = {
                "invocation_id": invocation_id,
                "run_id": args[0],
                "node_run_id": args[1],
                "attempt_id": args[2],
                "binding_id": args[3],
                "effect_key": args[4],
                "status": args[5],
                "revision": args[6],
                "created_at": args[7],
                "payload": args[8],
            }
            return "UPDATE 1"
        raise AssertionError(f"unexpected query: {query!r}")

    async def fetch(self, query: str, *args: Any) -> list[_Row]:
        # ``list_effect`` issues two shapes: the physical-visit lookup filters
        # ``node_run_id=$2`` (4 args); the logical-effect lookup issues a
        # 3-arg query with no node filter at all. Emulate the SQL faithfully:
        # a present filter binds its argument exactly (``node_run_id = NULL``
        # matches nothing -- the pre-#1194 defect), an absent filter matches
        # every NodeRun. Ordering mirrors ``ORDER BY created_at,
        # invocation_id ASC``.
        filters_node = "node_run_id=$2" in query
        if filters_node:
            run_id, node_run_id, binding_id, effect_key = args
        else:
            run_id, binding_id, effect_key = args
            node_run_id = None
        matches = [
            row
            for row in self._rows.values()
            if row["run_id"] == run_id
            and (not filters_node or row["node_run_id"] == node_run_id)
            and row["binding_id"] == binding_id
            and row["effect_key"] == effect_key
        ]
        matches.sort(key=lambda row: (row["created_at"], row["invocation_id"]))
        return [_Row(payload=row["payload"]) for row in matches]

    def seed(self, invocation: Invocation) -> None:
        self._rows[invocation.invocation_id] = {
            "invocation_id": invocation.invocation_id,
            "run_id": invocation.run_id,
            "node_run_id": invocation.node_run_id,
            "attempt_id": invocation.attempt_id,
            "binding_id": invocation.binding.binding_id,
            "effect_key": invocation.effect_key,
            "status": invocation.status.value,
            "revision": invocation.revision,
            "created_at": invocation.created_at.timestamp(),
            "payload": invocation.model_dump_json(),
        }


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


async def test_pg_invocation_store_create_active_effect_conflict_raises_unsafe_retry() -> None:
    """`ON CONFLICT DO NOTHING` has no explicit target, so it also catches the
    partial-unique-index collision on an already-active effect; `_find_effect`
    then finds the matching row and this is reported as an unsafe retry, not a
    generic already-exists error."""

    pool = _FakePgInvocationPool()
    pool.seed(_invocation())
    store = PgInvocationStore(pool)

    from maistro.capabilities.invocation import UnsafeEffectRetry

    with pytest.raises(UnsafeEffectRetry, match="active or completed"):
        await store.create(_invocation())


async def test_pg_invocation_store_create_id_collision_without_a_matching_effect_raises_value_error() -> (
    None
):
    """A bare `invocation_id` collision that does not share the new row's
    run/node/binding/effect_key -- so `_find_effect` finds nothing -- is a
    generic already-exists error, the defensive fallback for a primary-key
    collision unrelated to the effect-uniqueness guarantee."""

    pool = _FakePgInvocationPool()
    pool.seed(
        _invocation(run_id="run-other", node_run_id="node-run-other", effect_key="test:elsewhere")
    )
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


async def test_pg_invocation_store_list_effect_without_node_run_id_spans_node_runs() -> None:
    """``node_run_id=None`` is the logical-effect identity (#1194): one
    history per (run, binding, effect_key) across every physical NodeRun.
    The SQL must match rows, not bind NULL -- ``NULL = NULL`` is not true in
    SQL, so the pre-fix query returned nothing and the completed-Invocation
    dedup plus the ``UnsafeEffectRetry`` guard silently never fired on
    Postgres."""
    pool = _FakePgInvocationPool()
    store = PgInvocationStore(pool)
    await store.create(
        _invocation(
            invocation_id="inv-1",
            node_run_id="node-run-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    await store.create(
        _invocation(
            invocation_id="inv-2",
            node_run_id="node-run-2",
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    await store.create(
        _invocation(
            invocation_id="inv-3",
            node_run_id="node-run-9",
            run_id="run-other",
            created_at=datetime(2026, 1, 3, tzinfo=UTC),
        )
    )

    logical = await store.list_effect(
        run_id="run-1",
        node_run_id=None,
        binding_id="binding-1",
        effect_key="test:pg-store",
    )

    assert [item.invocation_id for item in logical] == ["inv-1", "inv-2"]
    # The physical-visit lookup is unchanged: one NodeRun's rows only.
    visit = await store.list_effect(
        run_id="run-1",
        node_run_id="node-run-2",
        binding_id="binding-1",
        effect_key="test:pg-store",
    )
    assert [item.invocation_id for item in visit] == ["inv-2"]


async def test_pg_invocation_store_logical_invoke_replays_completed_effect_across_node_runs() -> (
    None
):
    """The production dedup path on Postgres (#1194): a harness retry carries
    a new NodeRun/Attempt but ``logical_effect=True``, so the completed
    Invocation is returned without a second provider dispatch or INSERT --
    exactly the row the pre-fix ``node_run_id = NULL`` query could not find."""
    pool = _FakePgInvocationPool()
    service = InvocationExecutionService(store=PgInvocationStore(pool))
    dispatches = 0

    async def resolver(_binding: Binding) -> _Provider:
        return _Provider()

    async def execute(_provider: _Provider, _request: object) -> dict[str, str]:
        nonlocal dispatches
        dispatches += 1
        return {"handle_id": "handle-1"}

    first = await service.invoke(
        binding=_resolved_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="harness:dispatch",
        request={"task": "same logical work"},
        resolver=resolver,
        executor=execute,
        logical_effect=True,
    )
    assert dispatches == 1

    replay = await service.invoke(
        binding=_resolved_binding(),
        run_id="run-1",
        # Lease loss / retry: new NodeRun and Attempt, same logical effect.
        node_run_id="node-run-2",
        attempt_id="attempt-2",
        effect_key="harness:dispatch",
        request={"task": "same logical work"},
        resolver=resolver,
        executor=execute,
        logical_effect=True,
    )

    assert dispatches == 1
    assert replay.invocation_id == first.invocation_id
    assert replay.status is InvocationStatus.COMPLETED
    assert len(pool._rows) == 1


async def test_pg_invocation_store_logical_invoke_blocks_running_effect_from_another_node_run() -> (
    None
):
    """The ``UnsafeEffectRetry`` guard must also see across NodeRuns on
    Postgres: a live ``RUNNING`` Invocation for the logical effect blocks a
    second dispatch whose outcome cannot be proven absent (#1194)."""
    pool = _FakePgInvocationPool()
    store = PgInvocationStore(pool)
    created = await store.create(
        _invocation(
            invocation_id="inv-live",
            node_run_id="node-run-1",
            effect_key="harness:dispatch",
            status=InvocationStatus.RUNNING,
        )
    )
    await store.save(created)
    service = InvocationExecutionService(store=store)

    async def resolver(_binding: Binding) -> _Provider:
        return _Provider()

    async def execute(_provider: _Provider, _request: object) -> dict[str, str]:
        raise AssertionError("a live logical effect must not dispatch again")

    with pytest.raises(UnsafeEffectRetry, match="has outcome 'running'"):
        await service.invoke(
            binding=_resolved_binding(),
            run_id="run-1",
            node_run_id="node-run-2",
            attempt_id="attempt-2",
            effect_key="harness:dispatch",
            request={"task": "same logical work"},
            resolver=resolver,
            executor=execute,
            logical_effect=True,
        )


async def test_container_selects_the_pg_invocation_ledger_when_a_pool_is_wired() -> None:
    """The container's durable-backend precedence picks the canonical ledger.

    With a PostgreSQL pool wired, capability Invocations must live in
    ``PgInvocationStore`` (schema ensured), not the SQLite or in-memory
    fallback -- the ledger the replay contract reconciles against.
    """

    class _Transaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: Any) -> None:
            return None

    class _SchemaConnection:
        async def execute(self, query: str, *args: Any) -> str:
            assert "capability_invocations" in query
            return "OK"

        def transaction(self) -> _Transaction:
            return _Transaction()

    class _Acquire:
        def __init__(self) -> None:
            self._conn = _SchemaConnection()

        async def __aenter__(self) -> _SchemaConnection:
            return self._conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class _SchemaPool(_FakePgInvocationPool):
        def acquire(self) -> _Acquire:
            return _Acquire()

    store = await _wire_capability_invocations(pg_pool=_SchemaPool(), db_pool=None)

    assert isinstance(store, PgInvocationStore)
    assert await store.get("inv-absent") is None
