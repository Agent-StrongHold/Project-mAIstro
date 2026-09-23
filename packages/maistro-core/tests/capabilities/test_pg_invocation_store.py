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

from typing import Any

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.capabilities.pg_invocation_store import PgInvocationStore


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

    async def fetch(self, _query: str, *args: Any) -> list[_Row]:
        run_id, node_run_id, binding_id, effect_key = args
        matches = [
            row
            for row in self._rows.values()
            if row["run_id"] == run_id
            and row["node_run_id"] == node_run_id
            and row["binding_id"] == binding_id
            and row["effect_key"] == effect_key
        ]
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
