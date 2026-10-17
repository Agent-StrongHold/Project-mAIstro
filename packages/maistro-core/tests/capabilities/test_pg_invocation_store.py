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
from maistro.capabilities.effect_context import new_postgres_effect_context
from maistro.capabilities.invocation import (
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.pg_invocation_store import PgInvocationStore


class _Provider:
    name = "provider-a"
    slot = "external_write"
    trust_tier = "trusted"


def _finished_at() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)


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
            row = {
                "invocation_id": invocation_id,
                "run_id": args[1],
                "node_run_id": args[2],
                "attempt_id": args[3],
                "binding_id": args[4],
                "effect_key": args[5],
                "effect_scope": args[6],
                "status": args[7],
                "revision": args[8],
                "created_at": args[9],
                "payload": args[10],
            }
            if self._claim_conflicts(row):
                # Emulates migration 035's partial unique index
                # uq_capability_invocation_active_effect on
                # (run_id, effect_scope, binding_id, effect_key): the store's
                # INSERT binds the normalized logical scope, so a concurrent
                # NodeRun visit of the same stable effect collides here and
                # `ON CONFLICT DO NOTHING` returns no row.
                return None
            self._rows[invocation_id] = row
            return _Row(invocation_id=invocation_id)
        if "ORDER BY created_at DESC" in query:
            # `_find_effect`: latest row for this run/logical-scope/binding/effect_key.
            run_id, effect_scope, binding_id, effect_key = args
            matches = [
                row
                for row in self._rows.values()
                if row["run_id"] == run_id
                and row["effect_scope"] == effect_scope
                and row["binding_id"] == binding_id
                and row["effect_key"] == effect_key
            ]
            return _Row(payload=matches[-1]["payload"]) if matches else None
        if "SELECT payload FROM capability_invocations WHERE invocation_id" in query:
            row = self._rows.get(args[0])
            return _Row(payload=row["payload"]) if row is not None else None
        raise AssertionError(f"unexpected query: {query!r}")

    _CLAIM_STATUSES = frozenset({"created", "running", "completed", "unknown"})

    def _claim_conflicts(self, candidate: dict[str, Any]) -> bool:
        """Emulates migration 035's partial unique index: every non-FAILED
        status occupies the claim, so only a proven-FAILED record admits a
        new physical dispatch under the same logical identity."""

        if candidate["status"] not in self._CLAIM_STATUSES:
            return False
        return any(
            row["status"] in self._CLAIM_STATUSES
            and row["run_id"] == candidate["run_id"]
            and row["effect_scope"] == candidate["effect_scope"]
            and row["binding_id"] == candidate["binding_id"]
            and row["effect_key"] == candidate["effect_key"]
            for row in self._rows.values()
        )

    async def execute(self, query: str, *args: Any) -> str:
        if "UPDATE capability_invocations" in query:
            invocation_id, revision = args[-2], args[-1]
            existing = self._rows.get(invocation_id)
            if existing is None or existing["revision"] != revision:
                return "UPDATE 0"
            # The real UPDATE does not touch the effect_scope column; the
            # fake must preserve it the same way or the emulated claim index
            # would lose the scope after any terminal write.
            self._rows[invocation_id] = {
                "invocation_id": invocation_id,
                "run_id": args[0],
                "node_run_id": args[1],
                "attempt_id": args[2],
                "binding_id": args[3],
                "effect_key": args[4],
                "effect_scope": existing["effect_scope"],
                "status": args[5],
                "revision": args[6],
                "created_at": args[7],
                "payload": args[8],
            }
            return "UPDATE 1"
        raise AssertionError(f"unexpected query: {query!r}")

    async def fetch(self, query: str, *args: Any) -> list[_Row]:
        if "effect_scope=$2" in query:
            run_id, scope_value, binding_id, effect_key = args
            scope_field = "effect_scope"
        elif "binding_id=$2 AND effect_key=$3" in query:
            # The node_run_id=None audit read: the discriminator is dropped
            # from the SQL entirely (binding it to NULL would match no row),
            # so three bound params select every node run under the run.
            run_id, binding_id, effect_key = args
            matches = [
                row
                for row in self._rows.values()
                if row["run_id"] == run_id
                and row["binding_id"] == binding_id
                and row["effect_key"] == effect_key
            ]
            # Insertion order stands in for the real query's `ORDER BY created_at`.
            return [_Row(payload=row["payload"]) for row in matches]
        else:
            run_id, scope_value, binding_id, effect_key = args
            scope_field = "node_run_id"
        matches = [
            row
            for row in self._rows.values()
            if row["run_id"] == run_id
            and row[scope_field] == scope_value
            and row["binding_id"] == binding_id
            and row["effect_key"] == effect_key
        ]
        # Insertion order stands in for the real query's `ORDER BY created_at`.
        return [_Row(payload=row["payload"]) for row in matches]

    def seed(self, invocation: Invocation) -> None:
        self._rows[invocation.invocation_id] = {
            "invocation_id": invocation.invocation_id,
            "run_id": invocation.run_id,
            "node_run_id": invocation.node_run_id,
            "attempt_id": invocation.attempt_id,
            "binding_id": invocation.binding.binding_id,
            "effect_key": invocation.effect_key,
            "effect_scope": invocation.effect_scope or invocation.node_run_id,
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


async def test_pg_invocation_store_list_effect_without_a_node_run_spans_node_runs() -> None:
    """The pg twin of the develop contract: ``node_run_id=None`` spans every
    node run under the run for the binding+effect_key pair. The store must
    drop the discriminator from the SQL rather than bind NULL (an
    ``= NULL`` comparison matches no row), mirroring the SQLite store."""

    pool = _FakePgInvocationPool()
    store = PgInvocationStore(pool)
    # Only a proven-FAILED prior admits a second claim under the same logical
    # identity (the emulated migration-035 partial unique index), so the
    # first visit is a recorded failure and the retry lands under a new node
    # run -- exactly the history the audit read must span.
    await store.create(
        _invocation(
            invocation_id="inv-1",
            effect_key="test:pg-store",
            status=InvocationStatus.FAILED,
            error="EffectNotApplied: the provider proved nothing was applied",
            finished_at=_finished_at(),
        )
    )
    await store.create(
        _invocation(
            invocation_id="inv-2",
            node_run_id="node-run-2",
            effect_key="test:pg-store",
        )
    )
    await store.create(
        _invocation(invocation_id="inv-3", effect_key="test:other-effect"),
    )

    spanned = await store.list_effect(
        run_id="run-1",
        node_run_id=None,
        binding_id="binding-1",
        effect_key="test:pg-store",
    )

    assert [item.invocation_id for item in spanned] == ["inv-1", "inv-2"]


async def test_pg_invocation_store_rejects_cross_node_run_active_effect_claim() -> None:
    """The durable claim index is keyed by the logical effect identity
    (``effect_scope or node_run_id``, migration 035), so a second NodeRun
    visit of the same stable effect cannot create its own Invocation while
    the first visit's outcome is still active (#42, #1194). The conflicting
    row is reported as an unsafe retry -- the effect-contract error -- and
    not as a generic id collision."""

    pool = _FakePgInvocationPool()
    store = PgInvocationStore(pool)
    await store.create(
        _invocation(
            invocation_id="inv-1",
            effect_scope="run-1:charge:order-42",
            status=InvocationStatus.RUNNING,
        )
    )

    with pytest.raises(UnsafeEffectRetry, match="active or completed"):
        await store.create(
            _invocation(
                invocation_id="inv-2",
                node_run_id="node-run-2",
                attempt_id="attempt-2",
                effect_scope="run-1:charge:order-42",
            )
        )


async def test_pg_invocation_store_completed_claim_refuses_later_cross_node_visit() -> None:
    """The claim predicate covers every non-FAILED status, so a visit that
    arrives after the first visit terminalized cannot slip a second physical
    dispatch past the index: the insert collides and the outcome surfaces as
    the effect-contract error (``InvocationExecutionService`` re-reads the
    scoped history on this error and returns the completed result)."""

    pool = _FakePgInvocationPool()
    store = PgInvocationStore(pool)
    await store.create(
        _invocation(
            invocation_id="inv-1",
            effect_scope="run-1:charge:order-42",
            status=InvocationStatus.COMPLETED,
            finished_at=_finished_at(),
        )
    )

    with pytest.raises(UnsafeEffectRetry, match="active or completed"):
        await store.create(
            _invocation(
                invocation_id="inv-2",
                node_run_id="node-run-2",
                attempt_id="attempt-2",
                effect_scope="run-1:charge:order-42",
            )
        )

    # A proven-FAILED record keeps the retry door open for a new visit.
    failed = _invocation(
        invocation_id="inv-3",
        node_run_id="node-run-3",
        attempt_id="attempt-3",
        effect_scope="run-1:charge:order-42",
        status=InvocationStatus.FAILED,
        finished_at=_finished_at(),
        error="provider proved effect not applied",
    )
    await store.create(failed)
    assert failed.invocation_id == "inv-3"


async def test_pg_service_deduplicates_logical_effect_across_node_run_visits() -> None:
    """The durable PostgreSQL counterpart of the in-memory contract: a
    completed prior Invocation for the same logical effect is returned to a
    later NodeRun visit through the scoped history read, without another
    provider call, and the persisted record keeps the dispatching visit's
    identities."""

    class _Provider:
        name = "provider-a"
        slot = "external_write"
        trust_tier = "trusted"

    async def resolver(_binding: Binding) -> _Provider:
        return _Provider()

    calls = 0

    async def execute(_provider: _Provider, request: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"committed": request}

    binding = Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        capability="external_write",
    )
    service = InvocationExecutionService(store=PgInvocationStore(_FakePgInvocationPool()))

    async def visit(node_run_id: str, attempt_id: str) -> Invocation:
        return await service.invoke(
            binding=binding,
            run_id="run-1",
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key="charge:order-42",
            effect_scope="run-1:charge:order-42",
            request={"order": 42},
            resolver=resolver,
            executor=execute,
        )

    first = await visit("node-run-1", "attempt-1")
    replay = await visit("node-run-2", "attempt-2")

    assert calls == 1
    assert replay.invocation_id == first.invocation_id
    assert replay.node_run_id == "node-run-1"
    assert replay.attempt_id == "attempt-1"


def _event_schema_catalogue_rows(query: str) -> list[dict[str, Any]]:
    """Catalogue answers for the composition fixture's migrated Event table."""
    if "FROM pg_attribute a" in query:
        return [{"attname": "event_id", "data_type": "text", "can_insert": True}]
    return [{"columns": ["event_id"]}, {"columns": ["stream_id", "sequence"]}]


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

    executed: list[str] = []

    class _SchemaConnection:
        async def execute(self, query: str, *args: Any) -> str:
            # The live path ensures all three effect schemas, not only the
            # ledger's, so asserting that every statement names
            # `capability_invocations` was a property of the helper this test
            # used to call rather than of the composition it stands for.
            executed.append(query)
            return "OK"

        async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
            executed.append(query)
            return _event_schema_catalogue_rows(query)

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

    # Through the live composition path, not a helper only this test called.
    # `_wire_capability_invocations` selected the ledger on its own until the
    # effect context took that job over; keeping the test pointed at it left
    # a production function whose only caller was this line (vulture, #1195).
    context = await new_postgres_effect_context(_SchemaPool())

    assert isinstance(context.invocation_store, PgInvocationStore)
    assert any("capability_invocations" in q for q in executed), (
        "the ledger's schema was never ensured on the wired pool"
    )
    assert await context.invocation_store.get("inv-absent") is None


async def test_postgres_effect_context_reuses_already_selected_stores() -> None:
    """#1133 AC-8, the PostgreSQL leg of the injection contract covered above
    for SQLite: if the Container already selected durable Invocation/Event/
    Approval stores on this pool, the builder must thread those exact
    instances through rather than opening a second store behind them -- two
    objects reading and writing the same tables without knowing about each
    other.
    """
    from maistro.capabilities.approval_store import PgApprovalStore
    from maistro.events.pg_envelope import PgEventStore

    class _Transaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: Any) -> None:
            return None

    class _SchemaConnection:
        async def execute(self, query: str, *args: Any) -> str:
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

    pool = _SchemaPool()
    invocation_store = PgInvocationStore(pool)
    event_store = PgEventStore(pool)
    approvals = PgApprovalStore(pool)

    context = await new_postgres_effect_context(
        pool,
        invocation_store=invocation_store,
        event_store=event_store,
        approvals=approvals,
    )

    assert context.invocation_store is invocation_store
    assert context.event_store is event_store
    assert context.approval_store is approvals
