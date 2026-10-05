"""Coverage for maistro.capabilities.approval_store.PgApprovalStore (was 0%).

`test_durable_approval.py` exercises `InMemoryApprovalStore` and
`SqliteApprovalStore` against real backends (an in-process dict, a real
SQLite file), but nothing in this package ever constructed `PgApprovalStore`
or called `_approval_from_payload` -- the PostgreSQL leg of durable approvals
was entirely unexercised (#1362 diff-coverage gate).

Rather than requiring a live PostgreSQL server for logic this simple, this
uses the same FakePool/FakeConnection asyncpg test double as the other
Pg*Store suites (see `tests/persistence/test_pg_outcomes.py`,
`tests/security/test_pg_strikes.py`): record exact SQL + params and return
canned rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    DurableApproval,
    PgApprovalStore,
    _approval_from_payload,
)
from maistro.capabilities.slots.approval import ApprovalRequest


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class _TxnCtx:
    async def __aenter__(self) -> _TxnCtx:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetchrow_results: list[FakeRecord | None] = []

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.calls.append(Call("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return "UPDATE 1"

    def transaction(self) -> _TxnCtx:
        return _TxnCtx()


class _AcquireCtx:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakePool:
    """Supports both the top-level `fetchrow` `create`/`get`/`find_effect` use
    and the `acquire()` + `transaction()` pair `resolve` uses for its row lock.
    """

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        return await self._conn.fetchrow(query, *args)


@pytest.fixture
def conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def store(conn: FakeConnection) -> PgApprovalStore:
    return PgApprovalStore(FakePool(conn))


def _approval(*, request_id: str = "req-1", effect_key: str = "write:1") -> DurableApproval:
    request = ApprovalRequest(
        request_id=request_id,
        action="invoke:external_write",
        params={"request": {"value": 1}},
        tier="policy",
        requester="node-run-1",
    )
    return DurableApproval(
        request=request,
        workspace_id="ws-1",
        project_id="project-1",
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        binding_id="binding-1",
        effect_key=effect_key,
    )


# --------------------------------------------------------------------------
# create()
# --------------------------------------------------------------------------


async def test_create_returns_new_approval_when_insert_wins(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    approval = _approval()
    # `ON CONFLICT ... DO NOTHING RETURNING payload` returns a row exactly
    # when this call's insert is the one that lands.
    conn.queue_fetchrow({"payload": approval.model_dump_json()})

    created = await store.create(approval)

    assert created == approval
    call = conn.calls[0]
    assert call.method == "fetchrow"
    assert "INSERT INTO capability_approvals" in call.query
    assert "ON CONFLICT" in call.query
    assert call.args == (
        approval.request.request_id,
        approval.run_id,
        approval.node_run_id,
        approval.binding_id,
        approval.effect_key,
        approval.model_dump_json(),
    )


async def test_create_returns_the_racing_approval_on_conflict(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    """Two concurrent `create`s for the same effect: the loser's insert is
    swallowed by `ON CONFLICT DO NOTHING` (no RETURNING row), so it must read
    back and return the approval the winner actually persisted -- not raise,
    and not silently invent a second logical approval for one effect."""
    first = _approval(request_id="req-first")
    second = _approval(request_id="req-second")
    # First call (the insert attempt): no row, because the winner already
    # holds the unique (run_id, node_run_id, binding_id, effect_key) slot.
    conn.queue_fetchrow(None)
    # Second call (`find_effect`'s re-read): the winner's row.
    conn.queue_fetchrow({"payload": first.model_dump_json()})

    returned = await store.create(second)

    assert returned == first
    assert returned != second
    methods = [c.method for c in conn.calls]
    assert methods == ["fetchrow", "fetchrow"]
    assert "WHERE run_id=$1" in conn.calls[1].query


async def test_create_raises_when_conflict_row_is_gone_on_reread(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    """The insert reports a conflict but a re-read finds nothing -- a
    transient inconsistency this store refuses to paper over by returning
    the approval the caller asked to create."""
    approval = _approval()
    conn.queue_fetchrow(None)  # insert: conflict, no RETURNING row
    conn.queue_fetchrow(None)  # find_effect: nothing there either

    with pytest.raises(ValueError, match=f"{approval.request.request_id!r} already exists"):
        await store.create(approval)


# --------------------------------------------------------------------------
# get()
# --------------------------------------------------------------------------


async def test_get_returns_approval_when_row_found(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    approval = _approval()
    conn.queue_fetchrow({"payload": approval.model_dump_json()})

    found = await store.get(approval.request.request_id)

    assert found == approval
    assert "WHERE request_id=$1" in conn.calls[0].query
    assert conn.calls[0].args == (approval.request.request_id,)


async def test_get_returns_none_when_row_missing(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)

    assert await store.get("does-not-exist") is None


# --------------------------------------------------------------------------
# find_effect()
# --------------------------------------------------------------------------


async def test_find_effect_returns_approval_when_row_found(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    approval = _approval()
    conn.queue_fetchrow({"payload": approval.model_dump_json()})

    found = await store.find_effect(
        run_id="run-1", node_run_id="node-run-1", binding_id="binding-1", effect_key="write:1"
    )

    assert found == approval
    call = conn.calls[0]
    assert call.args == ("run-1", "node-run-1", "binding-1", "write:1")


async def test_find_effect_returns_none_when_row_missing(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)

    found = await store.find_effect(
        run_id="run-1", node_run_id="node-run-1", binding_id="binding-1", effect_key="nope"
    )

    assert found is None


# --------------------------------------------------------------------------
# resolve()
# --------------------------------------------------------------------------


async def test_resolve_raises_when_request_missing(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)

    with pytest.raises(KeyError, match="does not exist"):
        await store.resolve("missing-request", approved=True, actor="alice")

    assert [c.method for c in conn.calls] == ["fetchrow"]


async def test_resolve_returns_already_resolved_approval_without_rewriting_it(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    """A second resolution attempt on an already-settled approval must not
    overwrite the first decision -- idempotent re-delivery, not a silent
    flip from denied to approved or a second actor's name replacing the
    first."""
    already_resolved = _approval().model_copy(
        update={
            "status": ApprovalStatus.DENIED,
            "actor": "bob",
            "resolved_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    conn.queue_fetchrow({"payload": already_resolved.model_dump_json()})

    result = await store.resolve(already_resolved.request.request_id, approved=True, actor="alice")

    assert result.status is ApprovalStatus.DENIED
    assert result.actor == "bob"
    # No UPDATE was issued: the row lock read it, found it terminal, and
    # returned without a second write.
    assert [c.method for c in conn.calls] == ["fetchrow"]


async def test_resolve_updates_pending_approval_and_returns_it_resolved(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    pending = _approval()
    assert pending.status is ApprovalStatus.PENDING
    conn.queue_fetchrow({"payload": pending.model_dump_json()})

    resolved = await store.resolve(pending.request.request_id, approved=True, actor="alice")

    assert resolved.status is ApprovalStatus.APPROVED
    assert resolved.actor == "alice"
    assert resolved.resolved_at is not None
    select_call, update_call = conn.calls
    assert select_call.method == "fetchrow"
    assert "FOR UPDATE" in select_call.query
    assert update_call.method == "execute"
    assert "UPDATE capability_approvals SET payload=$1::jsonb" in update_call.query
    assert update_call.args[1] == pending.request.request_id
    # The row actually written carries the resolved status, not the pending
    # snapshot that was read.
    rewritten = DurableApproval.model_validate_json(update_call.args[0])
    assert rewritten.status is ApprovalStatus.APPROVED


async def test_resolve_rejects_blank_actor_before_touching_the_pool(
    store: PgApprovalStore, conn: FakeConnection
) -> None:
    with pytest.raises(ValueError, match="verified principal"):
        await store.resolve("some-request", approved=True, actor="   ")

    assert conn.calls == []


# --------------------------------------------------------------------------
# _approval_from_payload() -- the two shapes asyncpg can hand back a jsonb
# column in: a raw JSON string (no connection-level codec registered), or an
# already-decoded mapping (the `maistro.persistence` jsonb codec applied).
# --------------------------------------------------------------------------


def test_approval_from_payload_parses_a_json_string() -> None:
    approval = _approval()

    parsed = _approval_from_payload(approval.model_dump_json())

    assert parsed == approval


def test_approval_from_payload_parses_an_already_decoded_mapping() -> None:
    approval = _approval()

    parsed = _approval_from_payload(approval.model_dump(mode="json"))

    assert parsed == approval
