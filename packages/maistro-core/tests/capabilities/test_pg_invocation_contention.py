"""Real PostgreSQL effect admission and stale-write evidence for #42/#1194.

Unlike the adjacent SQL-shape fake, these tests use the migrated database and
independent connection pools. No test creates the claim index: losing the
migration's logical-effect uniqueness must fail the contention assertions.
Provider rendezvous happens after both services have read empty history, so
an in-process lock or a lucky sequential history read cannot prove admission.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    StaleInvocationUpdate,
    UnsafeEffectRetry,
)
from maistro.capabilities.pg_invocation_store import PgInvocationStore
from maistro.persistence import _register_json_codecs
from maistro.testing.postgres import postgres_dsn

pytestmark = pytest.mark.timeout(30)


class _Provider:
    name = "test-provider"
    slot = "external_write"
    trust_tier = "trusted"


@pytest.fixture
async def workers(pg_pool: Any) -> AsyncIterator[tuple[Any, Any, str]]:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    import asyncpg

    other = await asyncpg.create_pool(
        postgres_dsn(), min_size=1, max_size=2, init=_register_json_codecs
    )
    run_id = f"invocation-contention-{uuid4().hex}"
    try:
        yield pg_pool, other, run_id
    finally:
        await other.close()
        await pg_pool.execute("DELETE FROM capability_invocations WHERE run_id=$1", run_id)


def _binding() -> Binding:
    return Binding(
        binding_id="contention-binding",
        workspace_id="contention-workspace",
        project_id="contention-project",
        capability="external_write",
    )


def _candidate(run_id: str, visit: int, status: InvocationStatus) -> Invocation:
    return Invocation(
        run_id=run_id,
        node_run_id=f"node-visit-{visit}",
        attempt_id=f"attempt-{visit}",
        binding=ResolvedBinding.from_provider(_binding(), _Provider()),
        effect_key="charge",
        effect_scope="logical-charge",
        status=status,
        finished_at=(
            datetime.now(UTC)
            if status in {InvocationStatus.COMPLETED, InvocationStatus.UNKNOWN}
            else None
        ),
    )


@pytest.mark.parametrize(
    "status",
    [
        InvocationStatus.CREATED,
        InvocationStatus.RUNNING,
        InvocationStatus.COMPLETED,
        InvocationStatus.UNKNOWN,
    ],
)
async def test_database_claim_spans_physical_node_visits(
    workers: tuple[Any, Any, str], status: InvocationStatus
) -> None:
    first, second, run_id = workers
    stores = [PgInvocationStore(first), PgInvocationStore(second)]
    candidates = [_candidate(run_id, visit, status) for visit in (1, 2)]
    outcomes = await asyncio.gather(
        *(store.create(candidate) for store, candidate in zip(stores, candidates, strict=True)),
        return_exceptions=True,
    )
    accepted = [outcome for outcome in outcomes if isinstance(outcome, Invocation)]
    assert len(accepted) == 1, outcomes
    assert sum(isinstance(outcome, UnsafeEffectRetry) for outcome in outcomes) == 1, outcomes
    [winner] = accepted
    history = await stores[1].list_effect(
        run_id=run_id,
        node_run_id=None,
        binding_id=_binding().binding_id,
        effect_key="charge",
        effect_scope="logical-charge",
    )
    assert history == [winner]


@pytest.mark.parametrize("ambiguous", [False, True], ids=["completed", "unknown"])
async def test_racing_services_dispatch_once_and_fresh_service_reads_the_fact(
    workers: tuple[Any, Any, str], ambiguous: bool
) -> None:
    first, second, run_id = workers
    services = [
        InvocationExecutionService(store=PgInvocationStore(pool)) for pool in (first, second)
    ]
    both_read_empty = asyncio.Barrier(2)
    release_provider = asyncio.Event()
    dispatches: list[int] = []

    async def resolver(_binding: Binding) -> _Provider:
        await both_read_empty.wait()
        return _Provider()

    async def execute(_provider: Any, request: int) -> dict[str, str]:
        dispatches.append(request)
        await release_provider.wait()
        if ambiguous:
            raise ConnectionError("effect landed but the response was lost")
        return {"receipt": "charged-once"}

    def invoke(service: InvocationExecutionService, visit: int, resolve: Any) -> Any:
        return service.invoke(
            binding=_binding(),
            run_id=run_id,
            node_run_id=f"node-visit-{visit}",
            attempt_id=f"attempt-{visit}",
            effect_key="charge",
            effect_scope="logical-charge",
            request=visit,
            resolver=resolve,
            executor=execute,
        )

    tasks = [
        asyncio.create_task(invoke(service, visit, resolver))
        for visit, service in enumerate(services, start=1)
    ]
    try:
        # The provider cannot finish yet. The first settled call must be the
        # losing worker, refused by PostgreSQL rather than by a terminal read.
        done, pending = await asyncio.wait(tasks, timeout=10, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == 1 and len(pending) == 1
        [loser] = done
        assert isinstance(loser.exception(), UnsafeEffectRetry)
        release_provider.set()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        assert len(dispatches) == 1
        winner_visit = dispatches[0]
        winner_outcome = outcomes[winner_visit - 1]
        if ambiguous:
            assert isinstance(winner_outcome, ConnectionError)
        else:
            assert isinstance(winner_outcome, Invocation)
            assert winner_outcome.result == {"receipt": "charged-once"}
    finally:
        release_provider.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Fresh service/store objects have no shared service lock or cached result.
    # Read via the other pool, not the winner's connection, then revisit under
    # a third physical identity. Neither a success nor ambiguity may dispatch.
    pool = second if winner_visit == 1 else first
    store = PgInvocationStore(pool)
    [record] = await store.list_effect(
        run_id=run_id,
        node_run_id=None,
        binding_id=_binding().binding_id,
        effect_key="charge",
        effect_scope="logical-charge",
    )
    assert record.node_run_id == f"node-visit-{winner_visit}"
    assert record.attempt_id == f"attempt-{winner_visit}"
    assert record.status is (InvocationStatus.UNKNOWN if ambiguous else InvocationStatus.COMPLETED)

    async def must_not_resolve(_binding: Binding) -> _Provider:
        pytest.fail("durable history must settle replay before provider selection")

    restarted = InvocationExecutionService(store=store)
    if ambiguous:
        with pytest.raises(UnsafeEffectRetry, match="unknown"):
            await invoke(restarted, 3, must_not_resolve)
    else:
        replay = await invoke(restarted, 3, must_not_resolve)
        assert replay == record
    assert dispatches == [winner_visit]


async def test_stale_worker_cannot_overwrite_a_terminal_fact(
    workers: tuple[Any, Any, str],
) -> None:
    first, second, run_id = workers
    writer, other = PgInvocationStore(first), PgInvocationStore(second)
    original = await writer.create(_candidate(run_id, 1, InvocationStatus.RUNNING))
    stale = await other.get(original.invocation_id)
    assert stale is not None
    terminal = original.model_copy(
        update={
            "status": InvocationStatus.COMPLETED,
            "finished_at": datetime.now(UTC),
            "result": {"receipt": "durable"},
        }
    )
    accepted = await writer.save(terminal)
    with pytest.raises(StaleInvocationUpdate):
        await other.save(
            stale.model_copy(
                update={"status": InvocationStatus.UNKNOWN, "finished_at": datetime.now(UTC)}
            )
        )
    assert await other.get(original.invocation_id) == accepted
    assert accepted.revision == original.revision + 1
