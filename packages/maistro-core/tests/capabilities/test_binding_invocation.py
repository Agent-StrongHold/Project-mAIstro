from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.binding_store import (
    BindingDisabled,
    BindingNotFound,
    BindingScopeDenied,
    InMemoryBindingStore,
    PgBindingStore,
    RevocableBindingStore,
    SqliteBindingStore,
    _scope_checked,
)
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.governed_invocation import InvocationDenied
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


async def _resolver(binding: Binding) -> _Provider:
    assert binding.capability == "external_write"
    return _Provider()


@pytest.mark.asyncio
async def test_unconfigured_effect_context_denies_before_provider_call() -> None:
    effects = new_effect_context()
    binding = await effects.bindings.put(_binding())
    calls = 0

    async def execute(_provider: _Provider, _request: Any) -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(InvocationDenied, match="policy unavailable"):
        await effects.invocations.invoke(
            binding=binding,
            run_id="run-unconfigured",
            node_run_id="node-unconfigured",
            attempt_id="attempt-unconfigured",
            effect_key="effect-unconfigured",
            request={"write": True},
            resolver=_resolver,
            executor=execute,
        )

    assert calls == 0
    events = await effects.event_store.list_stream("workspace:ws-1")
    assert events[-1].type == "capability.invocation.policy_decision"
    assert events[-1].payload["decision"] == "deny"
    assert events[-1].payload["rule"] == "invocation.unconfigured"


def _binding(*, provider_name: str = "") -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="external_write",
        provider_name=provider_name,
        config={"mode": "safe"},
        credential_refs=("credential-1",),
        policy_refs=("policy-1",),
    )


def test_resolved_binding_records_provider_and_rejects_pin_mismatch() -> None:
    provider = _Provider()
    resolved = ResolvedBinding.from_provider(_binding(), provider)

    assert resolved.binding_id == "binding-1"
    assert resolved.provider_name == "provider-a"
    assert resolved.provider_trust_tier == "trusted"
    assert resolved.config == {"mode": "safe"}
    assert resolved.credential_refs == ("credential-1",)
    assert resolved.policy_refs == ("policy-1",)

    with pytest.raises(ValueError, match="pins provider"):
        ResolvedBinding.from_provider(_binding(provider_name="provider-b"), provider)


@pytest.mark.asyncio
async def test_completed_effect_is_deduplicated_across_attempt_recovery() -> None:
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def execute(_provider: _Provider, request: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"committed": request}

    first = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="ticket:create:123",
        request={"title": "one"},
        resolver=_resolver,
        executor=execute,
    )
    replay = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="ticket:create:123",
        request={"title": "one"},
        resolver=_resolver,
        executor=execute,
    )

    assert calls == 1
    assert first.status is InvocationStatus.COMPLETED
    assert replay.invocation_id == first.invocation_id
    assert replay.attempt_id == "attempt-1"


@pytest.mark.asyncio
async def test_unknown_external_outcome_blocks_automatic_retry() -> None:
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def ambiguous(_provider: _Provider, _request: Any) -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("connection lost after dispatch")

    with pytest.raises(ConnectionError, match="connection lost"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="payment:capture:456",
            request={"amount": 10},
            resolver=_resolver,
            executor=ambiguous,
        )

    history = await store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="binding-1",
        effect_key="payment:capture:456",
    )
    assert history[-1].status is InvocationStatus.UNKNOWN

    with pytest.raises(UnsafeEffectRetry, match="manual/reconciliation evidence"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-2",
            effect_key="payment:capture:456",
            request={"amount": 10},
            resolver=_resolver,
            executor=ambiguous,
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_proven_not_applied_effect_can_retry_as_new_invocation() -> None:
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def execute(_provider: _Provider, _request: Any) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EffectNotApplied("provider rejected before commit")
        return "committed"

    with pytest.raises(EffectNotApplied, match="before commit"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="issue:create:789",
            request={"title": "retryable"},
            resolver=_resolver,
            executor=execute,
        )

    second = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="issue:create:789",
        request={"title": "retryable"},
        resolver=_resolver,
        executor=execute,
    )
    history = await store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="binding-1",
        effect_key="issue:create:789",
    )

    assert calls == 2
    assert [item.status for item in history] == [
        InvocationStatus.FAILED,
        InvocationStatus.COMPLETED,
    ]
    assert [item.attempt_id for item in history] == ["attempt-1", "attempt-2"]
    assert second.result == "committed"


# --- InMemoryBindingStore: identity and scope resolution (#55) -------------


@pytest.mark.asyncio
async def test_binding_identity_is_immutable_across_re_registration() -> None:
    store = InMemoryBindingStore()
    first = await store.put(_binding())

    # Re-registering the exact same definition is idempotent...
    again = await store.put(first)
    assert again == first

    # ...but a changed definition behind the same id is refused rather than
    # silently widening the authority the id already grants.
    changed = _binding(provider_name="provider-b")
    with pytest.raises(ValueError, match="immutable and already registered"):
        await store.put(changed)


@pytest.mark.asyncio
async def test_resolve_requires_every_scope_field() -> None:
    store = InMemoryBindingStore()
    await store.put(_binding())

    with pytest.raises(BindingScopeDenied, match="workspace_id is required"):
        await store.resolve(
            "binding-1",
            workspace_id="",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )


@pytest.mark.asyncio
async def test_revoked_binding_cannot_be_recreated_or_resolved() -> None:
    store = InMemoryBindingStore()
    binding = await store.put(_binding())
    await store.revoke(binding.binding_id)

    with pytest.raises(BindingNotFound, match="has been revoked"):
        await store.resolve(
            binding.binding_id,
            workspace_id="ws-1",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )
    with pytest.raises(BindingNotFound, match="has been revoked"):
        await store.put(binding)


@pytest.mark.asyncio
async def test_resolve_of_an_unregistered_binding_is_not_found() -> None:
    store = InMemoryBindingStore()

    with pytest.raises(BindingNotFound, match="'binding-404' is not registered"):
        await store.resolve(
            "binding-404",
            workspace_id="ws-1",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )


@pytest.mark.asyncio
async def test_resolve_of_a_disabled_binding_refuses_instead_of_authorizing() -> None:
    store = InMemoryBindingStore()
    await store.put(_binding().model_copy(update={"disabled": True}))

    with pytest.raises(BindingDisabled, match="'binding-1' is disabled"):
        await store.resolve(
            "binding-1",
            workspace_id="ws-1",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"project_id": "project-2"}, "belongs to Project 'project-1'"),
        ({"node_id": "node-2"}, "is restricted to Node 'node-1'"),
        ({"capability": "external_read"}, "authorizes Capability 'external_write'"),
    ],
)
async def test_resolve_denies_each_scope_mismatch_by_name(
    overrides: dict[str, str], fragment: str
) -> None:
    store = InMemoryBindingStore()
    await store.put(_binding())

    scope = {
        "workspace_id": "ws-1",
        "project_id": "project-1",
        "node_id": "node-1",
        "capability": "external_write",
    } | overrides

    with pytest.raises(BindingScopeDenied, match=fragment):
        await store.resolve("binding-1", **scope)


@pytest.mark.asyncio
async def test_unrestricted_node_binding_resolves_for_any_node() -> None:
    store = InMemoryBindingStore()
    await store.put(_binding().model_copy(update={"node_id": ""}))

    resolved = await store.resolve(
        "binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="any-node-at-all",
        capability="external_write",
    )
    assert resolved.binding_id == "binding-1"


def test_scope_checked_defends_against_a_blank_field_directly() -> None:
    """The public `resolve()` on every store validates required scope fields
    before ever reaching `_scope_checked` (see `_resolve`), so this loop is
    unreachable through the store API by construction -- it is a private
    belt-and-braces guard on the shared helper itself, exercised here as the
    pure function it is (mirrors the `_integrity_failure` pattern used for
    similarly-unreachable guards elsewhere in this package)."""

    with pytest.raises(BindingScopeDenied, match="node_id is required"):
        _scope_checked(
            _binding(),
            binding_id="binding-1",
            workspace_id="ws-1",
            project_id="project-1",
            node_id="",
            capability="external_write",
        )


# --- SqliteBindingStore: same immutable-authority contract, durably (#55) ---


@pytest.mark.asyncio
async def test_sqlite_binding_store_put_persists_and_reopen_resolves(tmp_path: Any) -> None:
    db_path = tmp_path / "bindings.db"
    binding = _binding()

    async with aiosqlite.connect(db_path) as conn:
        store = SqliteBindingStore(conn)
        await store.ensure_schema()
        persisted = await store.put(binding)
        assert persisted == binding

    async with aiosqlite.connect(db_path) as conn:
        reopened = SqliteBindingStore(conn)
        await reopened.ensure_schema()

        fetched = await reopened.get("binding-1")
        assert fetched == binding
        assert await reopened.get("binding-404") is None

        resolved = await reopened.resolve(
            "binding-1",
            workspace_id="ws-1",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )
        assert resolved.binding_id == "binding-1"


@pytest.mark.asyncio
async def test_sqlite_binding_store_put_is_idempotent_but_immutable() -> None:
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteBindingStore(conn)
        await store.ensure_schema()

        first = await store.put(_binding())
        # Re-registering the identical definition is a no-op read, not a
        # second insert -- the same immutability contract InMemoryBindingStore
        # enforces, now backed by durable storage.
        again = await store.put(first)
        assert again == first

        changed = _binding(provider_name="provider-b")
        with pytest.raises(ValueError, match="immutable and already registered"):
            await store.put(changed)


# --- PgBindingStore: same contract over a pooled asyncpg-shaped connection -


class _FakePgBindingPool:
    """Records exactly the `INSERT ... ON CONFLICT DO NOTHING` / `SELECT`
    shape `PgBindingStore` issues, without needing a live PostgreSQL server.

    Routes on the table name because the store now reads two of them: a fake
    that answered every `fetchval` from the bindings map reported each
    binding as revoked, since its payload is truthy.
    """

    def __init__(self) -> None:
        self._rows: dict[str, str] = {}
        self._revoked: set[str] = set()

    async def execute(self, query: str, *args: Any) -> str:
        binding_id = str(args[0])
        if "capability_binding_revocations" in query:
            self._revoked.add(binding_id)
            return "INSERT 0 1"
        if query.lstrip().upper().startswith("DELETE"):
            self._rows.pop(binding_id, None)
            return "DELETE 1"
        payload_json = str(args[-1])
        if binding_id not in self._rows:
            self._rows[binding_id] = payload_json
        return "INSERT 0 1"

    async def fetchval(self, query: str, *args: Any) -> str | int | None:
        binding_id = str(args[0])
        if "capability_binding_revocations" in query:
            return 1 if binding_id in self._revoked else None
        return self._rows.get(binding_id)

    def acquire(self) -> _FakePgAcquire:
        return _FakePgAcquire(self)

    def transaction(self) -> _FakePgTransaction:
        # The fake collapses pool and connection into one object, so the
        # acquired "connection" has to answer `transaction()` as asyncpg's
        # real Connection does.
        return _FakePgTransaction()

    def seed(self, binding: Binding) -> None:
        self._rows[binding.binding_id] = binding.model_dump_json()


class _FakePgTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: Any) -> None:
        return None


class _FakePgAcquire:
    """`revoke` writes both statements inside one acquired transaction."""

    def __init__(self, pool: _FakePgBindingPool) -> None:
        self._pool = pool

    async def __aenter__(self) -> _FakePgBindingPool:
        return self._pool

    async def __aexit__(self, *_args: Any) -> None:
        return None

    def transaction(self) -> _FakePgTransaction:
        return _FakePgTransaction()


@pytest.mark.asyncio
async def test_pg_binding_store_put_persists_new_binding() -> None:
    store = PgBindingStore(_FakePgBindingPool())
    binding = _binding()

    persisted = await store.put(binding)

    assert persisted == binding
    assert await store.get("binding-1") == binding
    assert await store.get("binding-404") is None


@pytest.mark.asyncio
async def test_pg_binding_store_put_is_idempotent_for_identical_redefinition() -> None:
    pool = _FakePgBindingPool()
    store = PgBindingStore(pool)
    first = await store.put(_binding())

    again = await store.put(first)

    assert again == first


@pytest.mark.asyncio
async def test_pg_binding_store_put_rejects_definition_change_behind_same_id() -> None:
    pool = _FakePgBindingPool()
    pool.seed(_binding())
    store = PgBindingStore(pool)

    with pytest.raises(ValueError, match="immutable and already registered"):
        await store.put(_binding(provider_name="provider-b"))


@pytest.mark.asyncio
async def test_pg_binding_store_put_reports_a_write_that_never_persisted() -> None:
    """`ON CONFLICT DO NOTHING` always leaves *some* row behind on a real
    PostgreSQL server -- if the follow-up SELECT still finds nothing, that is
    a store bug, not a legitimate outcome, and `put` refuses to return
    silently as if it had succeeded."""

    class _PoolThatNeverPersists:
        async def execute(self, _query: str, *args: Any) -> str:
            return "INSERT 0 0"

        async def fetchval(self, _query: str, *args: Any) -> str | None:
            return None

    store = PgBindingStore(_PoolThatNeverPersists())

    with pytest.raises(RuntimeError, match="was not persisted"):
        await store.put(_binding())


@pytest.mark.asyncio
async def test_pg_binding_store_resolve_delegates_to_shared_scope_check() -> None:
    store = PgBindingStore(_FakePgBindingPool())
    await store.put(_binding())

    resolved = await store.resolve(
        "binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="external_write",
    )

    assert resolved.binding_id == "binding-1"


# --- Durable revocation: the tombstone outlives the process (#1133, #846) ---


@pytest.mark.asyncio
async def test_sqlite_revocation_survives_reopening_the_database() -> None:
    """The whole point of doing it durably.

    `InMemoryBindingStore` could already revoke, but only "for this store's
    lifetime": a restart re-granted every withdrawn capability. An operator
    who cuts off a compromised Binding and then bounces the process has not
    cut off anything.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "bindings.db"

        async with aiosqlite.connect(db_path) as conn:
            store = SqliteBindingStore(conn)
            await store.ensure_schema()
            await store.put(_binding())
            await store.revoke("binding-1")

        async with aiosqlite.connect(db_path) as conn:
            reopened = SqliteBindingStore(conn)
            await reopened.ensure_schema()

            assert await reopened.get("binding-1") is None
            with pytest.raises(BindingNotFound, match="has been revoked"):
                await reopened.resolve(
                    "binding-1",
                    workspace_id="ws-1",
                    project_id="project-1",
                    node_id="node-1",
                    capability="external_write",
                )


@pytest.mark.asyncio
async def test_sqlite_revoked_identity_cannot_be_registered_again() -> None:
    """A tombstone, not a deletion.

    Deleting the row alone would let an actor that still remembers the id
    re-create it, which is the failure #846 exists to prevent -- so the
    denial has to outlive the record it forbids.
    """
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteBindingStore(conn)
        await store.ensure_schema()
        await store.put(_binding())
        await store.revoke("binding-1")

        with pytest.raises(BindingNotFound, match="has been revoked"):
            await store.put(_binding())


@pytest.mark.asyncio
async def test_sqlite_revoking_an_unknown_or_revoked_id_is_not_an_error() -> None:
    """Revocation is a desired end state, not a transition.

    An operator revoking twice, or revoking an id that was never registered,
    wants that id forbidden. Raising would make the safe action look failed
    and invite a retry loop around it.
    """
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteBindingStore(conn)
        await store.ensure_schema()

        await store.revoke("never-registered")
        await store.revoke("never-registered")

        with pytest.raises(BindingNotFound, match="has been revoked"):
            await store.resolve(
                "never-registered",
                workspace_id="ws-1",
                project_id="project-1",
                node_id="node-1",
                capability="external_write",
            )


@pytest.mark.asyncio
async def test_sqlite_revocation_denies_distinctly_from_an_unknown_identity() -> None:
    """ "Forbidden" and "never existed" must not read alike.

    Both raise BindingNotFound, but only one says why. An operator reading
    "no registered definition" for a Binding they deliberately withdrew
    cannot tell their revocation took effect.
    """
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteBindingStore(conn)
        await store.ensure_schema()
        await store.put(_binding())
        await store.revoke("binding-1")

        with pytest.raises(BindingNotFound) as revoked:
            await store.resolve(
                "binding-1",
                workspace_id="ws-1",
                project_id="project-1",
                node_id="node-1",
                capability="external_write",
            )
        with pytest.raises(BindingNotFound) as unknown:
            await store.resolve(
                "binding-404",
                workspace_id="ws-1",
                project_id="project-1",
                node_id="node-1",
                capability="external_write",
            )

        assert "has been revoked" in str(revoked.value)
        assert "has been revoked" not in str(unknown.value)


def test_every_binding_store_satisfies_the_revocable_contract() -> None:
    """The gap that blocked #1321.

    `CapabilityEffectContext` requires a `RevocableBindingStore`, and until
    now only the in-memory store could be one -- so wiring a durable effect
    context was a type error, which is the protocol correctly refusing to
    let a durable backend present a revoke surface it could not honour.
    """
    for store in (InMemoryBindingStore, SqliteBindingStore, PgBindingStore):
        assert hasattr(store, "revoke"), store.__name__
    assert "register" not in RevocableBindingStore.__protocol_attrs__, (
        "register is a synchronous in-memory boot seam; requiring it here is "
        "what made the contract unsatisfiable by any durable store"
    )


@pytest.mark.asyncio
async def test_pg_revocation_forbids_the_identity_for_every_replica() -> None:
    """One database, so a revocation issued anywhere is honoured everywhere.

    The in-memory store's revocation is process-local, which on a replicated
    deployment means a capability cut off on one worker stays live on the
    others.
    """
    pool = _FakePgBindingPool()
    store = PgBindingStore(pool)
    await store.put(_binding())

    await store.revoke("binding-1")

    assert await store.get("binding-1") is None
    with pytest.raises(BindingNotFound, match="has been revoked"):
        await store.resolve(
            "binding-1",
            workspace_id="ws-1",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )
    with pytest.raises(BindingNotFound, match="has been revoked"):
        await store.put(_binding())
