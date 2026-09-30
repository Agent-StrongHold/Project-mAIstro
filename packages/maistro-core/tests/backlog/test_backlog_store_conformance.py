"""One suite over all three BacklogItem stores (#82).

The in-memory reference is the definition of the contract; the SQLite and
PostgreSQL legs run the same bodies against the durable twins, because
"implements the same protocol as" being a docstring rather than a test is how
`PgStrikeTracker` came to be unusable (#134). The PostgreSQL leg needs a real
* migrated * server (run `alembic upgrade head` against it) and skips without
one; `MAISTRO_REQUIRE_PG_LEGS` turns that skip into a failure in the jobs that
own a server.

The semantics under test are the epic's acceptance surface: optimistic
concurrency with refused (never merged) conflicts (#82: conflict handling),
evidence-required closure (#101's terminal-state rule), decomposition with
cycle and open-child guards, attributed history that cannot drift from state,
and atomic claims that coordinate who may progress an item without ever
touching canonical Goal linkage (claims are not Goal ownership).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from maistro.backlog.model import (
    BacklogClaimError,
    BacklogClosureError,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogVersionConflict,
)
from maistro.backlog.store import UNSET, InMemoryBacklogStore
from maistro.testing.postgres import postgres_dsn

# --------------------------------------------------------------------------
# Backends


class _MemoryBackend:
    """The reference. One store object; an in-memory store is its own
    substrate, so durability assertions do not apply to it."""

    durable = False
    supports_concurrent_writers = False

    def __init__(self) -> None:
        self._store = InMemoryBacklogStore()

    async def store(self):
        return self._store

    async def close(self) -> None:
        return None


class _SqliteBackend:
    """A file on disk; each `store()` opens its own connection to it, so the
    durability assertions read through a connection the writer never used."""

    durable = True
    supports_concurrent_writers = False

    def __init__(self, tmp_path) -> None:
        self._path = tmp_path / "backlog.db"
        self._connections: list = []

    async def store(self):
        import aiosqlite

        from maistro.backlog.sqlite_store import SqliteBacklogStore

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        store = SqliteBacklogStore(conn)
        await store.ensure_schema()
        return store

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


class _PostgresBackend:
    """A migrated database; one pool, a store per test body."""

    durable = True
    supports_concurrent_writers = True

    def __init__(self, pool) -> None:
        self._pool = pool

    async def store(self):
        from maistro.backlog.pg_store import PgBacklogStore

        return PgBacklogStore(self._pool)

    async def close(self) -> None:
        return None


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def backend(request, tmp_path):
    if request.param == "memory":
        yield _MemoryBackend()
        return

    if request.param == "sqlite":
        made = _SqliteBackend(tmp_path)
        yield made
        await made.close()
        return

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL backlog-store leg cannot run and must not be "
                "silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    asyncpg = pytest.importorskip("asyncpg")
    # min_size=2: a one-connection pool serialises every caller by itself, and
    # the concurrent-claim test below would then pass with the row lock
    # removed -- proving only that the pool was the bottleneck.
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    try:
        yield _PostgresBackend(pool)
    finally:
        await pool.close()


# --------------------------------------------------------------------------
# Bodies


async def test_create_get_roundtrip_is_isolated(backend) -> None:
    store = await backend.store()
    workspace = uuid.uuid4().hex[:12]
    item = await store.create_item(
        workspace_id=workspace,
        title="Cut backlog authority over",
        actor="human:blake",
        details="After the DB/service/UI/Agent path is verified.",
        tags=("engine", "m3-c"),
        milestone="M3-C",
        package="maistro-core",
        risk_notes="No partial migration may change authority early.",
        goal_id="goal-82",
        goal_revision=2,
        source="human",
    )
    assert item.status is BacklogItemStatus.OPEN
    assert item.version == 1
    got = await store.get_item(item.item_id)
    assert got == item
    # A mutated return value must never reach the store.
    got.title = "mutated"
    assert (await store.get_item(item.item_id)).title == "Cut backlog authority over"


async def test_get_absent_item_is_none_and_reads_raise_not_found(backend) -> None:
    store = await backend.store()
    assert await store.get_item("nope") is None
    with pytest.raises(BacklogItemNotFound):
        await store.events("nope")
    with pytest.raises(BacklogItemNotFound):
        await store.active_claim("nope")


async def test_update_bumps_version_and_stale_edit_is_refused_not_merged(backend) -> None:
    store = await backend.store()
    item = await store.create_item(
        workspace_id=uuid.uuid4().hex[:12], title="First", actor="human:a"
    )
    updated = await store.update_item(
        item.item_id,
        expected_version=1,
        actor="human:b",
        title="Second",
        milestone="M3-C",
    )
    assert updated.version == 2
    assert updated.title == "Second"
    assert updated.milestone == "M3-C"
    assert updated.updated_at >= item.updated_at

    with pytest.raises(BacklogVersionConflict) as conflict:
        await store.update_item(
            item.item_id,
            expected_version=1,  # stale: the store is at 2
            actor="human:b",
            title="Third",
        )
    assert conflict.value.current_version == 2
    # The refused edit changed nothing.
    assert (await store.get_item(item.item_id)).title == "Second"


async def test_clearable_fields_clear_and_unset_fields_are_untouched(backend) -> None:
    store = await backend.store()
    item = await store.create_item(
        workspace_id=uuid.uuid4().hex[:12],
        title="T",
        actor="human:a",
        milestone="M1",
        package="maistro-core",
        goal_id="goal-1",
        goal_revision=1,
    )
    updated = await store.update_item(
        item.item_id,
        expected_version=1,
        actor="human:a",
        milestone=None,  # clear
        package=UNSET,  # untouched
    )
    assert updated.milestone is None
    assert updated.package == "maistro-core"
    assert updated.goal_id == "goal-1"
    assert updated.version == 2


async def test_terminal_status_is_unreachable_through_update(backend) -> None:
    store = await backend.store()
    item = await store.create_item(workspace_id=uuid.uuid4().hex[:12], title="T", actor="human:a")
    with pytest.raises(ValueError, match="close_item"):
        await store.update_item(
            item.item_id,
            expected_version=1,
            actor="human:a",
            status=BacklogItemStatus.DONE,
        )


async def test_closure_requires_evidence(backend) -> None:
    store = await backend.store()
    item = await store.create_item(workspace_id=uuid.uuid4().hex[:12], title="T", actor="human:a")
    with pytest.raises(BacklogClosureError, match="closure evidence"):
        await store.close_item(
            item.item_id,
            expected_version=1,
            actor="human:a",
            outcome=BacklogItemStatus.DONE,
            closure_summary="done, trust me",
            evidence_refs=(),
        )
    with pytest.raises(BacklogClosureError, match="not a terminal outcome"):
        await store.close_item(
            item.item_id,
            expected_version=1,
            actor="human:a",
            outcome=BacklogItemStatus.OPEN,
            closure_summary="n/a",
            evidence_refs=("run-1",),
        )


async def test_close_reopen_cycle_records_evidence_and_history(backend) -> None:
    store = await backend.store()
    item = await store.create_item(workspace_id=uuid.uuid4().hex[:12], title="T", actor="human:a")
    closed = await store.close_item(
        item.item_id,
        expected_version=1,
        actor="human:a",
        outcome=BacklogItemStatus.DONE,
        closure_summary="shipped behind PR #1",
        evidence_refs=("run-abc", "docs/specs/SPEC-092626-1831"),
    )
    assert closed.status is BacklogItemStatus.DONE
    assert closed.closure is not None
    assert closed.closure.evidence_refs == ("run-abc", "docs/specs/SPEC-092626-1831")

    # Closing twice, or claiming a closed item, is refused.
    with pytest.raises(BacklogClosureError, match="already closed"):
        await store.close_item(
            item.item_id,
            expected_version=2,
            actor="human:a",
            outcome=BacklogItemStatus.DONE,
            closure_summary="again",
            evidence_refs=("x",),
        )
    with pytest.raises(BacklogClosureError, match="cannot be claimed"):
        await store.claim_item(item.item_id, claimed_by="agent:bot")

    reopened = await store.reopen_item(item.item_id, expected_version=2, actor="human:a")
    assert reopened.status is BacklogItemStatus.OPEN
    assert reopened.closure is None
    with pytest.raises(BacklogClosureError, match="not closed"):
        await store.reopen_item(item.item_id, expected_version=3, actor="human:a")

    actor_kinds = [(event.actor, event.kind.value) for event in await store.events(item.item_id)]
    assert actor_kinds == [
        ("human:a", "created"),
        ("human:a", "closed"),
        ("human:a", "reopened"),
    ]
    versions = [event.item_version for event in await store.events(item.item_id)]
    assert versions == sorted(versions)
    assert versions[-1] == 3


async def test_decomposition_guards(backend) -> None:
    store = await backend.store()
    workspace = uuid.uuid4().hex[:12]
    parent = await store.create_item(workspace_id=workspace, title="Parent", actor="human:a")
    child = await store.create_item(
        workspace_id=workspace, title="Child", actor="human:a", parent_id=parent.item_id
    )
    assert child.parent_id == parent.item_id
    # The parent's history records the decomposition (#101).
    decomposed = [
        event for event in await store.events(parent.item_id) if event.kind.value == "decomposed"
    ]
    assert [event.payload["child_id"] for event in decomposed] == [child.item_id]

    # Cycles are refused: re-parenting the parent under its own child would
    # make the child its own ancestor.
    with pytest.raises(ValueError, match="cycle"):
        await store.update_item(
            parent.item_id,
            expected_version=1,
            actor="human:a",
            parent_id=child.item_id,
        )

    # A terminal parent takes no new children.
    await store.close_item(
        child.item_id,
        expected_version=1,
        actor="human:a",
        outcome=BacklogItemStatus.DONE,
        closure_summary="done",
        evidence_refs=("run-1",),
    )
    await store.close_item(
        parent.item_id,
        expected_version=1,
        actor="human:a",
        outcome=BacklogItemStatus.DONE,
        closure_summary="done",
        evidence_refs=("run-1",),
    )
    with pytest.raises(BacklogClosureError, match="decompose a closed"):
        await store.create_item(
            workspace_id=workspace, title="Late child", actor="human:a", parent_id=parent.item_id
        )

    # A parent with open children cannot close.
    open_parent = await store.create_item(workspace_id=workspace, title="P2", actor="human:a")
    await store.create_item(
        workspace_id=workspace, title="C2", actor="human:a", parent_id=open_parent.item_id
    )
    with pytest.raises(BacklogClosureError, match="still open"):
        await store.close_item(
            open_parent.item_id,
            expected_version=1,
            actor="human:a",
            outcome=BacklogItemStatus.DONE,
            closure_summary="s",
            evidence_refs=("r",),
        )


async def test_decomposition_requires_same_workspace(backend) -> None:
    store = await backend.store()
    parent = await store.create_item(
        workspace_id=uuid.uuid4().hex[:12], title="Parent", actor="human:a"
    )
    with pytest.raises(ValueError, match="parent's Workspace"):
        await store.create_item(
            workspace_id=uuid.uuid4().hex[:12],
            title="Child",
            actor="human:a",
            parent_id=parent.item_id,
        )


async def test_list_filters(backend) -> None:
    store = await backend.store()
    workspace = uuid.uuid4().hex[:12]
    root_a = await store.create_item(
        workspace_id=workspace, title="A", actor="human:a", tags=("engine",)
    )
    root_b = await store.create_item(
        workspace_id=workspace, title="B", actor="human:a", tags=("conductor",)
    )
    child = await store.create_item(
        workspace_id=workspace, title="A.1", actor="human:a", parent_id=root_a.item_id
    )
    await store.update_item(
        root_b.item_id,
        expected_version=1,
        actor="human:a",
        status=BacklogItemStatus.BLOCKED,
    )

    roots = await store.list_items(workspace, roots_only=True)
    assert [item.item_id for item in roots] == [root_a.item_id, root_b.item_id]
    children = await store.list_items(workspace, parent_id=root_a.item_id)
    assert [item.item_id for item in children] == [child.item_id]
    blocked = await store.list_items(workspace, status=BacklogItemStatus.BLOCKED)
    assert [item.item_id for item in blocked] == [root_b.item_id]
    tagged = await store.list_items(workspace, tag="engine")
    assert [item.item_id for item in tagged] == [root_a.item_id]
    assert await store.list_items(uuid.uuid4().hex[:12]) == []


async def test_claim_is_exclusive_and_its_lifecycle_is_recorded(backend) -> None:
    store = await backend.store()
    item = await store.create_item(workspace_id=uuid.uuid4().hex[:12], title="T", actor="human:a")
    at = datetime.now(UTC)
    claim = await store.claim_item(item.item_id, claimed_by="agent:bot", lease_seconds=60, at=at)
    assert claim.is_active(at=at)
    with pytest.raises(BacklogClaimError) as already:
        await store.claim_item(item.item_id, claimed_by="agent:other", lease_seconds=60, at=at)
    assert already.value.claim.claim_id == claim.claim_id

    live = await store.active_claim(item.item_id, at=at)
    assert live is not None and live.claim_id == claim.claim_id

    # A claim is not an edit: content, version and Goal linkage are untouched.
    after = await store.get_item(item.item_id)
    assert after.version == item.version
    assert after.goal_id == item.goal_id
    assert after.updated_at == item.updated_at

    await store.extend_claim(
        item.item_id,
        claim_id=claim.claim_id,
        lease_seconds=600,
        actor="agent:bot",
        at=at,
    )
    assert (await store.active_claim(item.item_id, at=at)).lease_expires_at > (
        at + timedelta(seconds=60)
    )
    with pytest.raises(BacklogClaimError):
        await store.extend_claim(
            item.item_id,
            claim_id="not-the-claim",
            lease_seconds=600,
            actor="agent:other",
            at=at,
        )

    await store.release_claim(item.item_id, claim_id=claim.claim_id, actor="agent:bot", at=at)
    assert await store.active_claim(item.item_id, at=at) is None
    # The released claim frees the item for the next claimant.
    next_claim = await store.claim_item(
        item.item_id, claimed_by="agent:other", lease_seconds=60, at=at
    )
    assert next_claim.claim_id != claim.claim_id

    with pytest.raises(BacklogItemNotFound):
        await store.release_claim(item.item_id, claim_id=claim.claim_id, actor="x", at=at)

    kinds = [event.kind.value for event in await store.events(item.item_id)]
    assert kinds == ["created", "claimed", "lease_extended", "claim_released", "claimed"]


async def test_expired_lease_frees_the_item_without_a_release(backend) -> None:
    store = await backend.store()
    item = await store.create_item(workspace_id=uuid.uuid4().hex[:12], title="T", actor="human:a")
    at = datetime.now(UTC)
    await store.claim_item(item.item_id, claimed_by="agent:bot", lease_seconds=1, at=at)
    later = at + timedelta(seconds=2)
    assert await store.active_claim(item.item_id, at=later) is None
    re_claim = await store.claim_item(
        item.item_id, claimed_by="agent:other", lease_seconds=60, at=later
    )
    assert re_claim.claimed_by == "agent:other"


async def test_concurrent_claims_admit_exactly_one(backend) -> None:
    """Two claimants race; the store admits one and refuses the other.

    On PostgreSQL this exercises the `FOR UPDATE` serialisation point with two
    pool connections; on the single-writer backends it still asserts the
    contract, but cannot probe the interleaving.
    """
    store = await backend.store()
    item = await store.create_item(workspace_id=uuid.uuid4().hex[:12], title="T", actor="human:a")
    results = await asyncio.gather(
        store.claim_item(item.item_id, claimed_by="agent:a", lease_seconds=60),
        store.claim_item(item.item_id, claimed_by="agent:b", lease_seconds=60),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, BaseException)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], BacklogClaimError)
    live = await store.active_claim(item.item_id)
    assert live.claim_id == winners[0].claim_id


async def test_history_is_durably_tailed(backend) -> None:
    """A store the writer never used sees the item, its claim state and its
    events -- the restart-durability half of the epic's target capabilities."""
    if not backend.durable:
        pytest.skip("the reference has no substrate to reopen")
    store = await backend.store()
    workspace = uuid.uuid4().hex[:12]
    item = await store.create_item(workspace_id=workspace, title="Durable", actor="human:a")
    claim = await store.claim_item(item.item_id, claimed_by="agent:bot")
    await store.update_item(
        item.item_id,
        expected_version=1,
        actor="human:a",
        title="Durable after restart",
    )
    fresh = await backend.store()
    reread = await fresh.get_item(item.item_id)
    assert reread.title == "Durable after restart"
    assert reread.version == 2
    live = await fresh.active_claim(item.item_id)
    assert live is not None and live.claim_id == claim.claim_id
    assert [event.kind.value for event in await fresh.events(item.item_id)] == [
        "created",
        "claimed",
        "updated",
    ]


async def test_backlog_stores_import_no_rsi(backend) -> None:
    """The work-source service is backend-independent Workspace substrate:
    importing it must not import RSI (#82 exit condition)."""
    import sys

    store = await backend.store()
    await store.get_item("nope")
    assert not any(m == "maistro_rsi" or m.startswith("maistro_rsi.") for m in sys.modules)
