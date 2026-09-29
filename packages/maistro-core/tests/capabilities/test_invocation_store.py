from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.container import _wire_capability_effects


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
        effects = await _wire_capability_effects(
            effect_context=None,
            db_pool=conn,
            pg_pool=None,
            capability_bindings=(),
            capability_credentials=None,
        )
        assert isinstance(effects.invocation_store, SqliteInvocationStore)
        await effects.invocation_store.ensure_schema()


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


@pytest.mark.asyncio
async def test_in_memory_logical_admission_spans_node_runs() -> None:
    """Store-level admission identity for a logical effect is the whole Run.

    A retry under a new NodeRun must collide with the canonical active row
    (#1194); an ordinary physical effect keeps its per-NodeRun scope, so a
    different NodeRun is still a different admission.
    """
    store = InMemoryInvocationStore()
    binding = Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        capability="external_write",
    )
    resolved = ResolvedBinding.from_provider(binding, _Provider())
    await store.create(
        Invocation(
            invocation_id="inv-live",
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            binding=resolved,
            effect_key="harness:dispatch",
            logical_effect=True,
            status=InvocationStatus.RUNNING,
        )
    )

    with pytest.raises(UnsafeEffectRetry):
        await store.create(
            Invocation(
                invocation_id="inv-retry",
                run_id="run-1",
                node_run_id="node-run-2",
                attempt_id="attempt-2",
                binding=resolved,
                effect_key="harness:dispatch",
                logical_effect=True,
            )
        )

    # Physical admission keeps its per-visit scope: a different NodeRun's
    # ordinary effect is a different admission, not a collision.
    await store.create(
        Invocation(
            invocation_id="inv-physical",
            run_id="run-1",
            node_run_id="node-run-2",
            attempt_id="attempt-3",
            binding=resolved,
            effect_key="write:physical",
        )
    )


@pytest.mark.asyncio
async def test_sqlite_logical_admission_spans_node_runs_and_has_the_guard(tmp_path) -> None:
    """SQLite admission for a logical effect is Run-scoped (#1194).

    The transactional check and the ``uq_..._active_logical_effect`` partial
    unique index both exist: the check reports the collision inside one
    transaction, the index is the atomic cross-connection backstop.
    """
    async with aiosqlite.connect(tmp_path / "logical.db") as conn:
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
                invocation_id="inv-live",
                run_id="run-1",
                node_run_id="node-run-1",
                attempt_id="attempt-1",
                binding=resolved,
                effect_key="harness:dispatch",
                logical_effect=True,
                status=InvocationStatus.RUNNING,
            )
        )

        with pytest.raises(UnsafeEffectRetry):
            await store.create(
                Invocation(
                    invocation_id="inv-retry",
                    run_id="run-1",
                    node_run_id="node-run-2",
                    attempt_id="attempt-2",
                    binding=resolved,
                    effect_key="harness:dispatch",
                    logical_effect=True,
                )
            )

        cursor = await conn.execute("PRAGMA index_list(capability_invocations)")
        indexes = {str(row[1]) for row in await cursor.fetchall()}
        assert "uq_capability_invocation_active_logical_effect" in indexes


@pytest.mark.asyncio
async def test_sqlite_logical_effect_race_across_node_runs_dispatches_once(tmp_path) -> None:
    """#1194's reproduction: two services, one logical effect, new NodeRuns.

    A lease-loss retry mints a new NodeRun for the same logical work. Before
    the Run-scoped admission guard both workers passed admission (the
    physical unique index keyed on ``node_run_id``) and both dispatched the
    remote side effect: dispatches=2, invocations=2. Now exactly one
    dispatch happens, the loser is refused while the winner is live, and a
    later retry under another new NodeRun replays the completed winner.
    """
    db_path = tmp_path / "logical-race.db"
    async with aiosqlite.connect(db_path) as winner_conn, aiosqlite.connect(db_path) as loser_conn:
        winner_store = SqliteInvocationStore(winner_conn)
        loser_store = SqliteInvocationStore(loser_conn)
        await winner_store.ensure_schema()
        await loser_store.ensure_schema()
        winner = InvocationExecutionService(store=winner_store)
        loser = InvocationExecutionService(store=loser_store)
        binding = Binding(
            binding_id="binding-1",
            workspace_id="ws-1",
            project_id="project-1",
            capability="external_write",
        )
        released = asyncio.Event()
        winner_dispatched = asyncio.Event()
        dispatches: list[str] = []

        async def execute(_provider: _Provider, request: object) -> dict[str, str]:
            dispatches.append(str(request["task"]))
            winner_dispatched.set()
            await released.wait()
            return {"handle_id": "handle-1"}

        async def invoke(
            service: InvocationExecutionService, node_run_id: str, attempt_id: str
        ) -> Invocation:
            return await service.invoke(
                binding=binding,
                run_id="run-1",
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                effect_key="harness:dispatch",
                request={"task": "same logical work"},
                resolver=_resolver,
                executor=execute,
                logical_effect=True,
            )

        winner_task = asyncio.create_task(invoke(winner, "node-run-1", "attempt-1"))
        await asyncio.wait_for(winner_dispatched.wait(), timeout=10)

        # The winner is live and RUNNING: the retry under a new NodeRun is
        # refused because its outcome cannot be proven absent.
        with pytest.raises(UnsafeEffectRetry):
            await invoke(loser, "node-run-2", "attempt-2")
        assert dispatches == ["same logical work"]

        released.set()
        completed = await winner_task
        assert completed.status is InvocationStatus.COMPLETED

        history = await winner_store.list_effect(
            run_id="run-1",
            node_run_id=None,
            binding_id="binding-1",
            effect_key="harness:dispatch",
        )
        assert [item.invocation_id for item in history] == [completed.invocation_id]

        # Lease loss again after completion: same logical effect, another new
        # NodeRun -- the canonical row is replayed, not re-dispatched.
        replay = await invoke(loser, "node-run-3", "attempt-3")
        assert replay.invocation_id == completed.invocation_id
        assert dispatches == ["same logical work"]


@pytest.mark.asyncio
async def test_invoke_logical_admission_race_replays_completed_winner_across_node_runs() -> None:
    """The post-admission re-read must use the logical Run scope (#1194).

    A stale logical admission against a winner that completed under another
    NodeRun is a replay: the re-read spans NodeRuns and returns the accepted
    result instead of re-raising the race error.
    """
    binding = Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        capability="external_write",
    )
    completed = Invocation(
        invocation_id="inv-winner",
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        binding=ResolvedBinding.from_provider(binding, _Provider()),
        effect_key="harness:dispatch",
        logical_effect=True,
        status=InvocationStatus.COMPLETED,
        finished_at=datetime.now(UTC),
    )

    class _RacyLogicalStore:
        def __init__(self) -> None:
            self.read_scopes: list[str | None] = []

        async def list_effect(
            self, *, run_id: str, node_run_id: str | None, binding_id: str, effect_key: str
        ) -> list[Invocation]:
            self.read_scopes.append(node_run_id)
            # First read races empty; every later read sees the winner.
            if len(self.read_scopes) == 1:
                return []
            return [completed] if node_run_id is None else []

        async def create(self, invocation: Invocation) -> Invocation:
            raise UnsafeEffectRetry("effect 'harness:dispatch' already has an active Invocation")

    store = _RacyLogicalStore()
    service = InvocationExecutionService(store=store)  # type: ignore[arg-type]

    replay = await service.invoke(
        binding=binding,
        run_id="run-1",
        node_run_id="node-run-2",
        attempt_id="attempt-2",
        effect_key="harness:dispatch",
        request={"task": "same logical work"},
        resolver=_resolver,
        executor=_executor,
        logical_effect=True,
    )

    assert replay.invocation_id == "inv-winner"
    assert replay.status is InvocationStatus.COMPLETED
    # Both the racing read and the re-read used the Run-wide scope.
    assert store.read_scopes == [None, None]


# --- SqliteInvocationStore.claim: the three exits nothing was exercising ---


def _binding_and_resolved() -> tuple[Binding, ResolvedBinding]:
    binding = Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        capability="external_write",
    )
    return binding, ResolvedBinding.from_provider(binding, _Provider())


def _invocation(resolved: ResolvedBinding, invocation_id: str, **over: object) -> Invocation:
    fields: dict[str, object] = {
        "invocation_id": invocation_id,
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "binding": resolved,
        "effect_key": "write:claim",
    }
    fields.update(over)
    return Invocation(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_claim_returns_the_completed_prior_instead_of_dispatching(tmp_path) -> None:
    """A replay, not a race, and it must not hold the write lock to say so.

    `claim` takes BEGIN IMMEDIATE before reading history, so the path that
    finds a completed prior has to roll back explicitly. Returning without
    that leaves the database write lock held by a connection that has
    decided to do nothing, and the next writer blocks on it.
    """
    async with aiosqlite.connect(tmp_path / "claim.db") as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        _binding, resolved = _binding_and_resolved()
        await store.create(
            _invocation(
                resolved,
                "inv-done",
                status=InvocationStatus.COMPLETED,
                result="committed",
                finished_at=datetime.now(UTC),
            )
        )

        claimed = await store.claim(_invocation(resolved, "inv-new"))

        assert claimed.invocation_id == "inv-done"
        assert claimed.status is InvocationStatus.COMPLETED
        # The lock is released, so an unrelated write goes through rather than
        # blocking behind a transaction the claim never closed.
        await store.create(_invocation(resolved, "inv-other", effect_key="write:unrelated"))


@pytest.mark.asyncio
async def test_claim_refuses_a_non_terminal_prior_as_an_unsafe_retry(tmp_path) -> None:
    """RUNNING means the remote outcome cannot be proven absent.

    Only a FAILED prior -- one an adapter proved never applied -- is eligible
    for a new physical Invocation.
    """
    async with aiosqlite.connect(tmp_path / "claim.db") as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        _binding, resolved = _binding_and_resolved()
        await store.create(_invocation(resolved, "inv-live", status=InvocationStatus.RUNNING))

        with pytest.raises(UnsafeEffectRetry, match="running"):
            await store.claim(_invocation(resolved, "inv-second"))

        await store.create(_invocation(resolved, "inv-other", effect_key="write:unrelated"))


@pytest.mark.asyncio
async def test_claim_admits_after_a_failed_prior(tmp_path) -> None:
    """The one prior that is eligible: FAILED is `EffectNotApplied` evidence."""
    async with aiosqlite.connect(tmp_path / "claim.db") as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        _binding, resolved = _binding_and_resolved()
        await store.create(
            _invocation(
                resolved,
                "inv-failed",
                status=InvocationStatus.FAILED,
                error="EffectNotApplied: the provider proved nothing was applied",
                finished_at=datetime.now(UTC),
            )
        )

        claimed = await store.claim(_invocation(resolved, "inv-retry"))

        assert claimed.invocation_id == "inv-retry"


@pytest.mark.asyncio
async def test_claim_reports_a_lost_insert_race_as_an_unsafe_retry(tmp_path) -> None:
    """The partial unique index is the final guard, and its rejection must
    not surface as a raw sqlite3.IntegrityError.

    A caller that catches UnsafeEffectRetry to re-read canonical history
    would not catch an IntegrityError, so the loser of a cross-connection
    race would crash instead of replaying.
    """
    async with aiosqlite.connect(tmp_path / "claim.db") as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        _binding, resolved = _binding_and_resolved()
        await store.claim(_invocation(resolved, "inv-dup"))

        # A *different* effect_key, so the in-transaction history read finds
        # nothing and the claim proceeds to insert -- where the primary key
        # rejects it. That is the shape of a lost cross-connection race: the
        # winner's row is invisible to this reader but real to the index.
        with pytest.raises(UnsafeEffectRetry, match="already has an active or completed"):
            await store.claim(_invocation(resolved, "inv-dup", effect_key="write:elsewhere"))

        await store.create(_invocation(resolved, "inv-other", effect_key="write:unrelated"))


@pytest.mark.asyncio
async def test_claim_releases_the_write_lock_when_something_unexpected_raises(tmp_path) -> None:
    """The bare `except BaseException` is load-bearing, not defensive noise.

    Any escape from inside BEGIN IMMEDIATE that skips the rollback strands
    the database write lock on this connection for the process's life. A
    cancellation is the realistic case, and it is not an Exception.
    """
    async with aiosqlite.connect(tmp_path / "claim.db") as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        _binding, resolved = _binding_and_resolved()
        broken = _invocation(resolved, "inv-boom")

        original = store._row_values

        def _explode(_invocation_arg: Invocation) -> tuple[object, ...]:
            raise KeyboardInterrupt("interrupted mid-transaction")

        store._row_values = _explode  # type: ignore[method-assign]
        try:
            with pytest.raises(KeyboardInterrupt):
                await store.claim(broken)
        finally:
            store._row_values = original  # type: ignore[method-assign]

        # Proof the lock was released: this write would block otherwise.
        await store.create(_invocation(resolved, "inv-after"))
