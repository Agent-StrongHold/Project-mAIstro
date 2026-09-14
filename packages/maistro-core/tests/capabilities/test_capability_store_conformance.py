"""One behavioral suite over all three capability-effect backends (#1133).

The Container selects Binding/Invocation implementations from the configured
backend (`memory://`, ``sqlite:`` or PostgreSQL), so the governed effect
contract — Binding immutability, scope resolution, Invocation provenance,
failed-effect reopen, and the logical effect identity — has to hold on every
one of them. Before #1133 the behavior suite ran against in-memory stores only;
the durable backends were wired without ever answering the same questions.

One answer is deliberately allowed to differ. On ``memory://`` the logical
effect identity `(run_id, node_run_id, binding_id, effect_key)` is protected by
a process-local lock plus the governed service's read-before-create check,
which is acceptable exactly because a process-local store has no cross-process
meaning (#1133's stop condition). On SQLite and PostgreSQL it is a database
UNIQUE constraint, and `test_duplicate_logical_identity_is_database_enforced`
pins that directly: a second ``create`` with a fresh Invocation id but the same
logical identity must be rejected by the backend, not reconciled by a lock a
replica cannot see. That test runs on the durable legs only — and is the point
of the suite.

The PostgreSQL leg skips without ``MAISTRO_TEST_PG_DSN``. A skipped leg is
untested, not passing — which is how the durable half of this gap went
unnoticed. ``MAISTRO_REQUIRE_PG_LEGS`` is set by the CI job that owns a
postgres service: there, "no DSN" means the job is misconfigured and skipping
would leave it green with the whole point of #1133 unexercised. Everywhere
else (a laptop, the plain ``test`` job) skipping is the right answer. Tests
use unique identities per run, so the leg can share a migrated database
without contending with any other suite.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.binding_store import (
    BindingNotFound,
    BindingScopeDenied,
    InMemoryBindingStore,
    SqliteBindingStore,
)
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    Invocation,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import (
    PgInvocationStore,
    SqliteInvocationStore,
)

DSN = os.environ.get("MAISTRO_TEST_PG_DSN", "")
BACKENDS = ["memory", "sqlite", "postgres"]


def _require_postgres() -> str:
    """The DSN, or a skip — unless the caller declared a server is guaranteed.

    Same contract as the durable-event conformance suite (#135): the CI job
    that sets ``MAISTRO_REQUIRE_PG_LEGS`` owns a postgres service, so an empty
    DSN there is a misconfiguration that must fail rather than skip.
    """
    if DSN:
        return DSN
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the PostgreSQL leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the PostgreSQL leg needs a real server")


@dataclass(frozen=True)
class CapabilityStores:
    """One backend's Binding and Invocation authorities under test."""

    backend: str
    bindings: Any
    invocations: Any
    suffix: str

    @property
    def enforces_effect_identity_in_the_database(self) -> bool:
        """``memory://`` may stay process-local; the durable backends may not."""
        return self.backend != "memory"

    def unique(self, name: str) -> str:
        """A run-unique id: the durable legs may share one migrated database."""
        return f"{name}-{self.suffix}"


@pytest.fixture(params=BACKENDS)
async def stores(request: pytest.FixtureRequest, tmp_path: Any) -> AsyncIterator[Any]:
    """Yield one backend's stores; the PostgreSQL leg needs a migrated server."""
    backend = request.param
    suffix = uuid.uuid4().hex[:8]
    if backend == "memory":
        yield CapabilityStores(backend, InMemoryBindingStore(), InMemoryInvocationStore(), suffix)
        return
    if backend == "sqlite":
        import aiosqlite

        conn = await aiosqlite.connect(tmp_path / f"capability-{suffix}.sqlite3")
        try:
            bindings = SqliteBindingStore(conn)
            invocations = SqliteInvocationStore(conn)
            await bindings.ensure_schema()
            await invocations.ensure_schema()
            yield CapabilityStores(backend, bindings, invocations, suffix)
        finally:
            await conn.close()
        return

    import asyncpg

    pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=2)
    try:
        from maistro.capabilities.binding_store import PgBindingStore

        bindings = PgBindingStore(pool)
        invocations = PgInvocationStore(pool)
        await bindings.ensure_schema()
        await invocations.ensure_schema()
        yield CapabilityStores(backend, bindings, invocations, suffix)
    finally:
        await pool.close()


def _binding(stores) -> Binding:  # type: ignore[no-untyped-def]
    return Binding(
        binding_id=stores.unique("binding"),
        workspace_id=stores.unique("ws"),
        project_id=stores.unique("project"),
        node_id=stores.unique("node"),
        capability="external_write",
        config={"mode": "safe"},
        credential_refs=("credential-1",),
        policy_refs=("policy-1",),
    )


def _invocation(
    binding: Binding,
    effect_key: str,
    *,
    invocation_id: str,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    status: InvocationStatus = InvocationStatus.CREATED,
    created_at: datetime,
) -> Invocation:
    return Invocation(
        invocation_id=invocation_id,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        binding=ResolvedBinding(
            binding_id=binding.binding_id,
            capability=binding.capability,
            provider_name="provider-a",
            provider_trust_tier="trusted",
            config=binding.config,
            credential_refs=binding.credential_refs,
            policy_refs=binding.policy_refs,
        ),
        effect_key=effect_key,
        status=status,
        created_at=created_at,
        finished_at=created_at if status is InvocationStatus.FAILED else None,
    )


async def test_a_binding_round_trips_and_resolves_only_its_own_scope(stores) -> None:  # type: ignore[no-untyped-def]
    binding = _binding(stores)
    persisted = await stores.bindings.put(binding)

    assert persisted == binding
    assert await stores.bindings.get(binding.binding_id) == binding

    resolved = await stores.bindings.resolve(
        binding.binding_id,
        workspace_id=binding.workspace_id,
        project_id=binding.project_id,
        node_id=binding.node_id,
        capability=binding.capability,
    )
    assert resolved == binding

    with pytest.raises(BindingScopeDenied):
        await stores.bindings.resolve(
            binding.binding_id,
            workspace_id="someone-elses-workspace",
            project_id=binding.project_id,
            node_id=binding.node_id,
            capability=binding.capability,
        )
    with pytest.raises(BindingScopeDenied):
        await stores.bindings.resolve(
            binding.binding_id,
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            node_id=binding.node_id,
            capability="another-capability",
        )
    with pytest.raises(BindingNotFound):
        await stores.bindings.resolve(
            "binding-that-was-never-registered",
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            node_id=binding.node_id,
            capability=binding.capability,
        )


async def test_a_binding_definition_is_immutable_behind_its_id(stores) -> None:  # type: ignore[no-untyped-def]
    binding = _binding(stores)
    await stores.bindings.put(binding)

    widened = binding.model_copy(update={"capability": "everything_write"})
    with pytest.raises(ValueError, match="immutable"):
        await stores.bindings.put(widened)

    # The rejection kept the registered definition, not the widened one.
    assert await stores.bindings.get(binding.binding_id) == binding


async def test_an_invocation_round_trips_its_resolved_provider_provenance(stores) -> None:  # type: ignore[no-untyped-def]
    binding = _binding(stores)
    await stores.bindings.put(binding)
    invocation = _invocation(
        binding,
        effect_key="write:1",
        invocation_id=stores.unique("invocation-provenance"),
        run_id=stores.unique("run-provenance"),
        node_run_id=stores.unique("node-run-provenance"),
        attempt_id=stores.unique("attempt-provenance"),
        created_at=datetime.now(UTC),
    )

    persisted = await stores.invocations.create(invocation)
    stored = await stores.invocations.get(persisted.invocation_id)

    assert stored is not None
    assert stored.invocation_id == invocation.invocation_id
    assert stored.run_id == invocation.run_id
    assert stored.status is InvocationStatus.CREATED
    assert stored.effect_key == "write:1"
    assert stored.binding.provider_name == "provider-a"
    assert stored.binding.provider_trust_tier == "trusted"
    assert stored.binding.binding_id == binding.binding_id


async def test_list_effect_is_scoped_to_one_logical_identity(stores) -> None:  # type: ignore[no-untyped-def]
    binding = _binding(stores)
    await stores.bindings.put(binding)
    moment = datetime.now(UTC)
    run_id = stores.unique("run-history")
    node_run_id = stores.unique("node-run-history")
    first = _invocation(
        binding,
        effect_key="write:1",
        invocation_id=stores.unique("invocation-a"),
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=stores.unique("attempt-a"),
        created_at=moment,
    )
    second = _invocation(
        binding,
        effect_key="write:2",
        invocation_id=stores.unique("invocation-b"),
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=stores.unique("attempt-b"),
        created_at=moment + timedelta(seconds=1),
    )
    await stores.invocations.create(first)
    await stores.invocations.create(second)

    kwargs: dict[str, str] = {
        "run_id": run_id,
        "node_run_id": node_run_id,
        "binding_id": binding.binding_id,
    }
    history = await stores.invocations.list_effect(effect_key="write:1", **kwargs)
    assert [item.invocation_id for item in history] == [first.invocation_id]

    assert await stores.invocations.list_effect(effect_key="never-invoked", **kwargs) == []


async def test_a_failed_effect_reopens_as_its_replacement(stores) -> None:  # type: ignore[no-untyped-def]
    binding = _binding(stores)
    await stores.bindings.put(binding)
    moment = datetime.now(UTC)
    failed = _invocation(
        binding,
        effect_key="write:1",
        invocation_id=stores.unique("failed-invocation"),
        run_id=stores.unique("run-retry"),
        node_run_id=stores.unique("node-run-retry"),
        attempt_id=stores.unique("attempt-1"),
        status=InvocationStatus.FAILED,
        created_at=moment,
    )
    await stores.invocations.create(failed)

    replacement = _invocation(
        binding,
        effect_key="write:1",
        invocation_id=stores.unique("replacement-invocation"),
        run_id=failed.run_id,
        node_run_id=failed.node_run_id,
        attempt_id=stores.unique("attempt-2"),
        created_at=moment + timedelta(seconds=1),
    )
    reopened = await stores.invocations.reopen_failed(failed, replacement)

    assert reopened.invocation_id == replacement.invocation_id
    assert reopened.attempt_id == replacement.attempt_id
    history = await stores.invocations.list_effect(
        run_id=failed.run_id,
        node_run_id=failed.node_run_id,
        binding_id=binding.binding_id,
        effect_key="write:1",
    )
    assert history[-1].invocation_id == replacement.invocation_id
    if stores.enforces_effect_identity_in_the_database:
        # Durable stores keep one row per logical effect: the failed physical
        # attempt is replaced, not appended (#1133).
        assert [item.invocation_id for item in history] == [replacement.invocation_id]
        assert await stores.invocations.get(failed.invocation_id) is None
    else:
        # The process-local store keeps physical retry history for diagnostics.
        assert [item.invocation_id for item in history] == [
            failed.invocation_id,
            replacement.invocation_id,
        ]


async def test_reopen_refuses_when_the_prior_effect_is_not_failed(stores) -> None:  # type: ignore[no-untyped-def]
    binding = _binding(stores)
    await stores.bindings.put(binding)
    live = _invocation(
        binding,
        effect_key="write:1",
        invocation_id=stores.unique("live-invocation"),
        run_id=stores.unique("run-live"),
        node_run_id=stores.unique("node-run-live"),
        attempt_id=stores.unique("attempt-1"),
        created_at=datetime.now(UTC),
    )
    await stores.invocations.create(live)

    replacement = _invocation(
        binding,
        effect_key="write:1",
        invocation_id=stores.unique("replacement-invocation"),
        run_id=live.run_id,
        node_run_id=live.node_run_id,
        attempt_id=stores.unique("attempt-2"),
        created_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    with pytest.raises(UnsafeEffectRetry):
        await stores.invocations.reopen_failed(live, replacement)

    history = await stores.invocations.list_effect(
        run_id=live.run_id,
        node_run_id=live.node_run_id,
        binding_id=binding.binding_id,
        effect_key="write:1",
    )
    assert [item.invocation_id for item in history] == [live.invocation_id]


async def test_duplicate_logical_identity_is_database_enforced(stores) -> None:  # type: ignore[no-untyped-def]
    """Two creates of one logical effect must not both become authoritative.

    This is the #1133 defect that started the suite: a process-local lock plus
    a read-before-create check cannot protect an identity two replicas compute
    against. On a durable backend the second insert loses at the database —
    before any provider could be dispatched twice. `memory://` is exempt by
    design: its stores have no cross-process meaning, and the invariant names
    the *database* as the enforcement point.
    """
    if not stores.enforces_effect_identity_in_the_database:
        pytest.skip("memory:// is allowed process-local identity semantics")

    binding = _binding(stores)
    await stores.bindings.put(binding)
    moment = datetime.now(UTC)
    first = _invocation(
        binding,
        effect_key="write:1",
        invocation_id=stores.unique("first-replica-invocation"),
        run_id=stores.unique("run-race"),
        node_run_id=stores.unique("node-run-race"),
        attempt_id=stores.unique("attempt-1"),
        created_at=moment,
    )
    await stores.invocations.create(first)

    second = _invocation(
        binding,
        effect_key="write:1",
        invocation_id=stores.unique("second-replica-invocation"),
        run_id=first.run_id,
        node_run_id=first.node_run_id,
        attempt_id=stores.unique("attempt-2"),
        created_at=moment + timedelta(seconds=1),
    )
    with pytest.raises(Exception):  # noqa: B017 - sqlite3 vs asyncpg violation types
        await stores.invocations.create(second)

    history = await stores.invocations.list_effect(
        run_id=first.run_id,
        node_run_id=first.node_run_id,
        binding_id=binding.binding_id,
        effect_key="write:1",
    )
    assert [item.invocation_id for item in history] == [first.invocation_id]
