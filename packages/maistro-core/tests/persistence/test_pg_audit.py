"""Coverage for maistro.persistence.pg_audit.PgAuditLog (was 0%).

asyncpg.Pool/Connection are faked with the same in-process test double used
across the persistence test suite: records exact SQL + params, returns
canned rows, so tests assert on emitted SQL/params, not just "didn't raise".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.persistence.pg_audit import PgAuditLog
from maistro.types.security import AuditEntry


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetch_results: list[list[FakeRecord]] = []

    def queue_fetch(self, rows: list[dict[str, Any]]) -> None:
        self._fetch_results.append([FakeRecord(r) for r in rows])

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return "INSERT 0 1"


class FakePool:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)


class _AcquireCtx:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def log(conn: FakeConnection) -> PgAuditLog:
    return PgAuditLog(FakePool(conn))


@pytest.mark.asyncio
async def test_log_inserts_with_team_id_and_tool_name_defaults(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    entry = AuditEntry(
        boundary="tool_call",
        user_id="u1",
        agent_id="a1",
        tool_name="bash",
        verdict="allowed",
        detail="ok",
        trace_id="t1",
        request_id="r1",
    )
    await log.log(entry)
    assert len(conn.calls) == 1
    call = conn.calls[0]
    assert call.method == "execute"
    assert "INSERT INTO audit_log" in call.query
    assert call.args == (
        "tool_call",
        "u1",
        "",  # team_id getattr default
        "a1",
        "bash",
        "allowed",
        "ok",
        "t1",
        "r1",
    )


@pytest.mark.asyncio
async def test_log_tool_name_none_becomes_empty_string(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    entry = AuditEntry(boundary="b", user_id="u", agent_id="a", tool_name=None)
    await log.log(entry)
    call = conn.calls[0]
    assert call.args[4] == ""


@pytest.mark.asyncio
async def test_log_team_id_passthrough_when_present(log: PgAuditLog, conn: FakeConnection) -> None:
    entry = AuditEntry(boundary="b", user_id="u", team_id="team-9", agent_id="a")
    await log.log(entry)
    call = conn.calls[0]
    assert call.args[2] == "team-9"


@pytest.mark.asyncio
async def test_get_entries_no_filters_uses_where_true(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await log.get_entries()
    call = conn.calls[0]
    assert "WHERE TRUE" in call.query
    assert call.args == (100,)


@pytest.mark.asyncio
async def test_get_entries_user_id_filter_builds_param(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await log.get_entries(user_id="u1", limit=5)
    call = conn.calls[0]
    assert "user_id = $1" in call.query
    assert "LIMIT $2" in call.query
    assert call.args == ("u1", 5)


@pytest.mark.asyncio
async def test_get_entries_both_filters_combined_with_and(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await log.get_entries(user_id="u1", agent_id="a1")
    call = conn.calls[0]
    assert "user_id = $1 AND agent_id = $2" in call.query
    assert call.args == ("u1", "a1", 100)


@pytest.mark.asyncio
async def test_get_entries_returns_reconstructed_audit_entries(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    conn.queue_fetch(
        [
            {
                "timestamp": ts,
                "boundary": "tool_call",
                "user_id": "u1",
                "team_id": "team-1",
                "agent_id": "a1",
                "tool_name": "bash",
                "verdict": "allowed",
                "detail": "ok",
                "trace_id": "t1",
                "request_id": "r1",
            }
        ]
    )
    entries = await log.get_entries(user_id="u1")
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, AuditEntry)
    assert e.timestamp == ts
    assert e.boundary == "tool_call"
    assert e.user_id == "u1"
    assert e.team_id == "team-1"
    assert e.agent_id == "a1"
    assert e.tool_name == "bash"
    assert e.verdict == "allowed"
    assert e.detail == "ok"
    assert e.trace_id == "t1"
    assert e.request_id == "r1"


@pytest.mark.asyncio
async def test_get_entries_missing_optional_fields_default(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    conn.queue_fetch([{"timestamp": ts}])
    entries = await log.get_entries()
    e = entries[0]
    assert e.boundary == ""
    assert e.user_id == ""
    assert e.team_id == ""
    assert e.agent_id == ""
    assert e.tool_name is None
    assert e.verdict == "allowed"
    assert e.detail == ""
    assert e.trace_id == ""
    assert e.request_id == ""


def test_allowed_filter_columns_is_exactly_user_and_agent_id() -> None:
    from maistro.persistence.pg_audit import _ALLOWED_FILTER_COLUMNS

    assert frozenset({"user_id", "agent_id"}) == _ALLOWED_FILTER_COLUMNS


@pytest.mark.asyncio
async def test_get_entries_invalid_filter_column_raises(
    log: PgAuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allowlist guard is dead code via the public API today (only
    user_id/agent_id are accepted params, both allowlisted) — patch the
    allowlist itself to a smaller set so the guard's error branch actually
    executes, proving it works if a new filter column is ever added without
    updating the allowlist."""
    import maistro.persistence.pg_audit as pg_audit_module

    monkeypatch.setattr(pg_audit_module, "_ALLOWED_FILTER_COLUMNS", frozenset({"agent_id"}))
    with pytest.raises(ValueError, match="Invalid filter column: 'user_id'"):
        await log.get_entries(user_id="u1")
